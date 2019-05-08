# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GitilesTestApi(recipe_test_api.RecipeTestApi):

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