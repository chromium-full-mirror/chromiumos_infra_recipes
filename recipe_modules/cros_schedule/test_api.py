# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for testing with cros_schedule."""

from datetime import datetime, timedelta
import json

from recipe_engine import recipe_test_api


class CrosScheduleTestApi(recipe_test_api.RecipeTestApi):

  def test_chromiumdash_fetch_response(self, start_mstone=88, fetch_n=2,
                                       ltr_last_refresh_date=None,
                                       late_stable_date='2021-01-26T00:00:00'):

    def _make_mstone(inc_days=0, mstone=start_mstone):
      # Annoyingly, this doesn't contain the 'Z' suffix. We have to include
      # that before we parse as proto, but, this matches what chromiumdash
      # gives us.
      dates = {
          'final_beta_cut': '2021-01-12T00:00:00',
          'final_beta': '2021-01-13T00:00:00',
          'feature_freeze': '2020-10-30T00:00:00',
          'earliest_beta': '2020-12-03T00:00:00',
          'stable_refresh_first': '2021-02-02T00:00:00',
          'latest_beta': '2020-12-10T00:00:00',
          'owners': {
              'clank': 'Krishna Govind',
              'bling': 'Bindu Suvarna',
              'cros': None,
              'desktop': 'Srinivas Sista',
          },
          'stable_cut': '2021-01-12T00:00:00',
          'stable_refresh_second': '2021-02-16T00:00:00',
          'mstone': mstone,
          'stable_date': '2021-01-19T00:00:00',
          'ldaps': {
              'clank': 'govind',
              'bling': 'bindusuvarna',
              'cros': None,
              'desktop': 'srinivassista ',
          },
          'earliest_beta_ios': '2020-11-17T00:00:00',
          'branch_point': '2020-11-12T00:00:00',
      }
      if late_stable_date:
        dates['late_stable_date'] = late_stable_date
      if ltr_last_refresh_date:
        dates['ltr_last_refresh_date'] = ltr_last_refresh_date
      for k, v in dates.items():
        try:
          t = datetime.strptime(v, '%Y-%m-%dT%H:%M:%S')
          dates[k] = (t +
                      timedelta(days=inc_days)).strftime('%Y-%m-%dT%H:%M:%S')
        except (TypeError, ValueError):
          pass

      return dates

    stones_list = []
    mstone_period_days = 6 * 7
    for n, mstone in enumerate(range(start_mstone, start_mstone + fetch_n)):
      stones_list.append(
          _make_mstone(inc_days=mstone_period_days * n, mstone=mstone))
    response = {'mstones': stones_list}
    return json.dumps(response)
