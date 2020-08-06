# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test api for cros_prebuilts

This module provides helpers to make testing cros_prebuilts in Chrome OS recipes
simpler and more consistent.
"""

from recipe_engine import recipe_test_api

from PB.chromiumos.common import PackageIndexInfo, Profile


class CrosPrebuiltsApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing cros_prebuilts in Chrome OS Recipes."""

  def profile_or_default(self, profile):
    """Return a default profile if there is no profile."""
    return profile if profile and profile.name else Profile(name='base')

  def generate_snapshot_test_data_dict(self, snapshots, build_target, profile,
                                       gs_bucket):
    """Return the default test_data_dict for get_package_index_info.

    Args:
      snapshots (list[str]): List of snapshot git SHA strings, newest first.
      build_targets (BuildTarget): BuildTarget to fetch.
      profile (Profile): The profile for the build.
      gs_bucket (str): Google storage bucket where the prebuilts live.

    Returns:
      (dict) test_data_dict to use.
    """

    def add_info(ret, sha, num, build_target, profile, fname, location):
      profile = self.profile_or_default(profile)
      info = PackageIndexInfo(snapshot_sha=sha, snapshot_number=num,
                              build_target=build_target, profile=profile,
                              location=location)
      target = build_target.name
      ret.setdefault(sha, {}).setdefault(target,
                                         {}).setdefault(profile.name,
                                                        {})[fname] = info
      return ret

    ret = {}
    # Provide answers for at most 4 snapshots.
    for num, sha in enumerate(snapshots[:4]):
      add_info(
          ret, sha, 1009 - num, build_target, profile,
          '%s-kind-%d-postsubmit.json' % (build_target.name, 1009 - num),
          'gs://%s/board/%s/KIND-VER-888/packages' %
          (gs_bucket, build_target.name))

    return ret
