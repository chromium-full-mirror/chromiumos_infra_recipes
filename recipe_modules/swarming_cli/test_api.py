# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingCliTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the swarming CLI module."""

  def swarming_bot_step_test_data(self, dimensions):
    """Returns list of bots based on provided dimensions.

    Args:
      dimensions(dict): Dictionary of dimensions
    """
    test_data = {
        'cq': [{
            'bot_size': 'large',
            'bot_id': 'chromeos-ci-cq-us-central1-b-x1-0-igx0\n',
        },
               {
                   'bot_size': 'large',
                   'bot_id': 'chromeos-ci-cq-us-central1-b-x1-4-gaf9\n',
               }],
        'vmtest': [{
            'bot_size': 'large',
            'bot_id': 'chromeos-ci-vm-us-central1-b-x1-0-igx0\n',
        },
                   {
                       'bot_size': 'large',
                       'bot_id': 'chromeos-ci-vm-us-central1-b-x1-4-gaf9\n',
                   }],
    }
    step_data = ""
    if dimensions['role'] in test_data.keys():
      for bots in test_data[dimensions['role']]:
        if bots['bot_size'] == dimensions['bot_size']:
          step_data += bots['bot_id']
    return step_data
