# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to help on test cases that rely on gitiles module."""

import base64

from recipe_engine import recipe_test_api


class GitilesTestApi(recipe_test_api.RecipeTestApi):

  @recipe_test_api.mod_test_data
  @staticmethod
  def get_file(data):  # pragma: nocover
    return base64.b64encode(data)

  def test_fetch_revision_output(self):
    """Returns test output for gitiles-fetch-ref call.

      Returns:
        dict, as below
      """
    return {
        'branch': {
            'revision': 'abcd1234',
        },
    }
