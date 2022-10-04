# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS's Schedule."""

from datetime import datetime
import json
import six

from google.protobuf.json_format import Parse

from PB.chromiumos.chromiumdash import FetchMilestoneScheduleResponse

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class CrosScheduleApi(recipe_api.RecipeApi):
  """A module for reading, commiting, and manipulating the release schedule."""

  CHROMIUMDASH_FETCH_URL_TEMPLATE = (
      'https://chromiumdash.appspot.com/fetch_milestone_schedule?mstone={}&n={}'
  )

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
    query_url = self.CHROMIUMDASH_FETCH_URL_TEMPLATE.format(
        start_mstone, fetch_n)

    with self.m.step.nest('fetch chromiumdash schedule'):
      returned_data = self.m.easy.stdout_step(
          'curl fetch_milestone_schedule', ['curl', query_url],
          test_stdout=self.test_api.test_chromiumdash_fetch_response(
              start_mstone=start_mstone, fetch_n=fetch_n))

      # json_to_proto can't handle null/None values, so replace with empty
      # strings.
      returned_data = six.ensure_str(returned_data).replace('null', '""')

      # Validate you have real json and the expected number of records.
      try:
        json_data = json.loads(returned_data)
      except ValueError:
        raise StepFailure('fetch schedule response was not json')
      try:
        mstones_returned = len(json_data['mstones'])
      except KeyError:
        raise self.m.step.StepFailure('fetch schedule response json format bad')
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
