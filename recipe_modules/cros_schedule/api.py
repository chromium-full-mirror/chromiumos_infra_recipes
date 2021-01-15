# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS's Schedule."""

import json

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class CrosScheduleApi(recipe_api.RecipeApi):
  """A module for reading, commiting, and manipulating the release schedule."""

  CHROMIUMDASH_FETCH_URL_TEMPLATE = (
      'https://chromiumdash.appspot.com/fetch_milestone_schedule?mstone={}&n={}'
  )

  def _fetch_chromiumdash_schedule(self, start_mstone=None, fetch_n=10):
    """Return the json schedule from chromiumdash.

    Args:
      start_mstone (int): start with this milestone. Default: last branched
          milestone.
      fetch_n (int): Number of milestones to return. Default: 10.

    Returns:
      (str): JSON string representing the results of the query, or None.
    """
    start_mstone = start_mstone or self._get_last_mstone()
    query_url = self.CHROMIUMDASH_FETCH_URL_TEMPLATE.format(
        start_mstone, fetch_n)

    with self.m.step.nest('fetch chromiumdash schedule'):
      returned_data = self.m.easy.stdout_step(
          'curl fetch_milestone_schedule', ['curl', query_url],
          test_stdout=self.test_api.test_chromiumdash_fetch_response())
      # Validate you have real json and the expected number of records.
      try:
        json_data = json.loads(returned_data)
      except ValueError:
        raise StepFailure('fetch schedule response was not json')
      try:
        mstones_returned = len(json_data['mstones'])
      except Exception:
        raise self.m.step.StepFailure('fetch schedule response json format bad')
      if mstones_returned != fetch_n:
        raise self.m.step.StepFailure(
            'fetch schedule did not return expected number of mstones')

  def _get_last_mstone(self):
    """Gets the last branched milestone."""
    # TODO(crbug.com/1157948): Really impl.
    return 88
