# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_test_api


class CrosScheduleTestApi(recipe_test_api.RecipeTestApi):

  def test_chromiumdash_fetch_response(self, starting_stone=88, n_stones=2,
                                       value_overrides=None):

    def _make_mstone(**kwargs):
      return {
          'final_beta_cut':
              kwargs.get('final_beta_cut', '2021-01-12T00:00:00'),
          'final_beta':
              kwargs.get('final_beta', '2021-01-13T00:00:00'),
          'feature_freeze':
              kwargs.get('feature_freeze', '2020-10-30T00:00:00'),
          'earliest_beta':
              kwargs.get('earliest_beta', '2020-12-03T00:00:00'),
          'stable_refresh_first':
              kwargs.get('stable_refresh_first', '2021-02-02T00:00:00'),
          'latest_beta':
              kwargs.get('latest_beta', '2020-12-10T00:00:00'),
          'owners': {
              'clank': 'Krishna Govind',
              'bling': 'Bindu Suvarna',
              'cros': 'Marina Kazatcker',
              'desktop': 'Srinivas Sista',
          },
          'stable_cut':
              kwargs.get('stable_cut', '2021-01-12T00:00:00'),
          'stable_refresh_second':
              kwargs.get('stable_refresh_second', '2021-02-16T00:00:00'),
          'mstone':
              kwargs.get('mstone', 88),
          'late_stable_date':
              kwargs.get('late_stable_date', '2021-01-26T00:00:00'),
          'stable_date':
              kwargs.get('stable_date', '2021-01-19T00:00:00'),
          'ldaps': {
              'clank': 'govind',
              'bling': 'bindusuvarna',
              'cros': 'marinakz',
              'desktop': 'srinivassista ',
          },
          'earliest_beta_ios':
              kwargs.get('earliest_beta_ios', '2020-11-17T00:00:00'),
          'branch_point':
              kwargs.get('branch_point', '2020-11-12T00:00:00'),
      }

    value_overrides = value_overrides or {}
    stones_list = []
    for stone in range(starting_stone, starting_stone + n_stones):
      value_overrides.update({'mstone': stone})
      stones_list.append(_make_mstone(**value_overrides))
    response = {'mstones': stones_list}
    return json.dumps(response)
