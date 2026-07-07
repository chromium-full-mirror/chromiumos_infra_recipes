# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS's Schedule."""

from datetime import datetime
import json

from google.protobuf.json_format import Parse

from PB.chromiumos.chromiumdash import FetchMilestoneScheduleResponse

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


CHROMIUMDASH_SCHEDULE_FETCH_URL_TEMPLATE = (
    'https://chromiumdash.appspot.com/fetch_milestone_schedule?mstone={}&n={}')
CHROMIUMDASH_MSTONE_FETCH_URL_TEMPLATE = (
    'https://chromiumdash.appspot.com/fetch_milestones?mstone={}')

CHROME_BRANCH_TEST_DATA = json.dumps([{
    'angle_branch': '5615',
    'bling_ldap': 'govind',
    'bling_owner': 'Krishna Govind',
    'chromium_branch': '5615',
    'chromium_main_branch_hash': '9c6408ef696e83a9936b82bbead3d41c93c82ee4',
    'chromium_main_branch_position': 1109224,
    'clank_ldap': 'govind',
    'clank_owner': 'Krishna Govind',
    'cros_ldap': 'obenedict',
    'cros_owner': 'Benedict Oleforo',
    'dawn_branch': '5615',
    'desktop_ldap': 'srinivassista',
    'desktop_owner': 'Srinivas Sista',
    'devtools_branch': '5615',
    'milestone': 112,
    'pdfium_branch': '5615',
    'skia_branch': 'm112',
    'v8_branch': '11.2-lkgr',
    'webrtc_branch': '5615'
}])


class CrosScheduleApi(recipe_api.RecipeApi):
  """A module for reading, commiting, and manipulating the release schedule."""

  def json_to_proto(self, sched_str_json):
    """Returns a FetchMilestoneScheduleResponse from JSON repr."""
    # Hack in timezone component to the json to satisfy protobuf's parser.
    json_str = sched_str_json.replace('T00:00:00', 'T00:00:00Z')
    mstones = FetchMilestoneScheduleResponse()
    return Parse(json_str, mstones, ignore_unknown_fields=True)

  def fetch_chromiumdash_schedule(self, start_mstone=None, fetch_n=10):
    """Return the json schedule from chromiumdash.

    Args:
      start_mstone (int): start with this milestone. Default: last branched
          milestone.
      fetch_n (int): Number of milestones to return. Default: 10.

    Returns:
      (str): JSON string representing the results of the query, or None.
    """
    start_mstone = start_mstone or self.get_last_branched_mstone_n()
    query_url = CHROMIUMDASH_SCHEDULE_FETCH_URL_TEMPLATE.format(
        start_mstone, fetch_n)

    with self.m.step.nest('fetch chromiumdash schedule'):
      returned_data = self.m.easy.stdout_step(
          'curl fetch_milestone_schedule', ['curl', query_url],
          test_stdout=self.test_api.test_chromiumdash_fetch_response(
              start_mstone=start_mstone, fetch_n=fetch_n))

      # json_to_proto can't handle null/None values, so replace with empty
      # strings.
      returned_data = returned_data.decode().replace('null', '""')

      # Validate you have real json and the expected number of records.
      try:
        json_data = json.loads(returned_data)
      except ValueError as e:
        raise StepFailure('fetch schedule response was not json') from e
      try:
        mstones_returned = len(json_data['mstones'])
      except KeyError as e:
        raise self.m.step.StepFailure(
            'fetch schedule response json format bad') from e
      if mstones_returned != fetch_n:
        raise self.m.step.StepFailure(
            'fetch schedule did not return expected number of mstones')
      return returned_data

  def get_last_branched_mstone(self):
    """Gets the last branched milestone.

    Returns:
      A chromiumos.chromiumdash.FetchMilestoneScheduleResponse.

    Raises: StepFailure if not able to find mstone.
    """
    # Seed with an intial datapoint.
    start_mstone = 88
    start = datetime(2020, 11, 12)
    today = self.m.time.utcnow()

    # Guess how many to pull assuming a minimum 2 week mstone period (min 2).
    fetch_n = max(int((today - start).days / 14), 2)
    schedule_json = self.fetch_chromiumdash_schedule(start_mstone=start_mstone,
                                                     fetch_n=fetch_n)
    mstones = self.json_to_proto(schedule_json)
    mstones = sorted(mstones.mstones, key=lambda x: x.mstone)
    # Very lazy straight iteration (no use being much more clever).
    prev = None
    for mstone in mstones:
      if mstone.branch_point.ToDatetime() > today:
        # If we're already past the branch point, something's wrong.
        if prev is None:
          break
        return prev
      prev = mstone
    # Failed to find the mstone that is most recently branched.
    raise StepFailure('could not find milestone')

  def get_last_branched_mstone_n(self):
    """Gets the last branched milestone number as an int."""
    return self.get_last_branched_mstone().mstone

  def get_chrome_branch(self, mstone):
    """Get the associated chrome branch for a milestone.

    Args:
      mstone (int): Milestone to fetch.

    Returns:
      (str): The chromium branch number or None.
    """
    query_url = CHROMIUMDASH_MSTONE_FETCH_URL_TEMPLATE.format(mstone)

    with self.m.step.nest('fetch chrome branch from chromiumdash'):
      returned_data = self.m.easy.stdout_step(
          'curl fetch_milestones', ['curl', query_url],
          test_stdout=CHROME_BRANCH_TEST_DATA)

      try:
        json_data = json.loads(returned_data)
      except ValueError as e:
        raise StepFailure('fetch milestone response was not json') from e
      try:
        mstone = json_data[0]
      except Exception as e:
        raise self.m.step.StepFailure(
            'fetch milestone response json format bad') from e
      return mstone.get('chromium_branch', None)

  def fetch_chromiumdash_milestones(self, only_branched=False):
    """Return the milestones from chromiumdash as a list of dicts.

    Args:
      only_branched (bool): If True, only fetch branched milestones.

    Returns:
      (list[dict]): Parsed JSON list representing the results of the query.
    """
    query_url = 'https://chromiumdash.appspot.com/fetch_milestones'
    if only_branched:
      query_url += '?only_branched=true'

    with self.m.step.nest('fetch chromiumdash milestones'):
      returned_data = self.m.easy.stdout_step(
          'curl fetch_milestones', ['curl', query_url],
          test_stdout=CHROME_BRANCH_TEST_DATA)

      if isinstance(returned_data, bytes):
        returned_data = returned_data.decode()

      try:
        return json.loads(returned_data)
      except ValueError as e:
        raise StepFailure('fetch milestones response was not json') from e
