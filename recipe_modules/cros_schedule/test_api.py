# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from datetime import datetime, timedelta
import json

from recipe_engine import recipe_test_api


class CrosScheduleTestApi(recipe_test_api.RecipeTestApi):

  def test_chromiumdash_fetch_response(self, start_mstone=88, fetch_n=2):

    def _make_mstone(inc_days=0, mstone=start_mstone):
      dates = {
          'final_beta_cut': '2021-01-12T00:00:00Z',
          'final_beta': '2021-01-13T00:00:00Z',
          'feature_freeze': '2020-10-30T00:00:00Z',
          'earliest_beta': '2020-12-03T00:00:00Z',
          'stable_refresh_first': '2021-02-02T00:00:00Z',
          'latest_beta': '2020-12-10T00:00:00Z',
          'owners': {
              'clank': 'Krishna Govind',
              'bling': 'Bindu Suvarna',
              'cros': 'Marina Kazatcker',
              'desktop': 'Srinivas Sista',
          },
          'stable_cut': '2021-01-12T00:00:00Z',
          'stable_refresh_second': '2021-02-16T00:00:00Z',
          'mstone': mstone,
          'late_stable_date': '2021-01-26T00:00:00Z',
          'stable_date': '2021-01-19T00:00:00Z',
          'ldaps': {
              'clank': 'govind',
              'bling': 'bindusuvarna',
              'cros': 'marinakz',
              'desktop': 'srinivassista ',
          },
          'earliest_beta_ios': '2020-11-17T00:00:00Z',
          'branch_point': '2020-11-12T00:00:00Z',
      }
      for k, v in dates.items():
        try:
          t = datetime.strptime(v, '%Y-%m-%dT%H:%M:%SZ')
          dates[k] = (t +
                      timedelta(days=inc_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        except TypeError, ValueError:
          pass

      return dates

    stones_list = []
    mstone_period_days = 6 * 7
    for n, mstone in enumerate(range(start_mstone, start_mstone + fetch_n)):
      stones_list.append(
          _make_mstone(inc_days=mstone_period_days * n, mstone=mstone))
    response = {'mstones': stones_list}
    return json.dumps(response)
