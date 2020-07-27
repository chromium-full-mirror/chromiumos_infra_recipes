# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test api for cros_prebuilts

This module provides helpers to make testing cros_prebuilts in Chrome OS recipes
simpler and more consistent.
"""

from recipe_engine import recipe_test_api

from PB.chromiumos.common import PackageIndexInfo


class CrosPrebuiltsApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing cros_prebuilts in Chrome OS Recipes."""

  def generate_snapshot_test_data_dict(self, snapshots, build_targets,
                                       gs_bucket):
    """Return the default test_data_dict for get_package_index_info.

    Args:
      snapshots (list[str]): List of snapshot git SHA strings, newest first.
      build_targets (list[BuildTarget]): List of BuildTargets to fetch.
      gs_bucket (str): Google storage bucket where the prebuilts live.

    Returns:
      (dict) test_data_dict to use.
    """

    def add_info(ret, sha, num, build_target, fname, location):
      target = build_target.name
      ret.setdefault(sha, {}).setdefault(target, {})[fname] = PackageIndexInfo(
          snapshot_sha=sha, snapshot_number=num, build_target=build_target,
          location=location)
      return ret

    ret = {}
    # Make a copy of snapshots, and make it 4 elements in length, extending with
    # the final element if needed.
    shas = (snapshots[:] + snapshots[-1:] * 3)[:4]
    # Everything has a prebuilt for the fourth sha.
    for bt in build_targets:
      # Everything has a prebuilt in the fourth snapshot.
      add_info(ret, shas[3], 1001, bt, '%s-kind-1001-postsubmit.json' % bt.name,
               'gs://%s/board/%s/KIND-VER-888/packages' % (gs_bucket, bt.name))

    # The first build_target given has a prebuilt in the second snapshot.
    bt = build_targets[0]
    add_info(ret, shas[1], 1003, bt, '%s-kind-1003-postsubmit.json' % bt.name,
             'gs://%s/board/%s/KIND-VER-888/packages' % (gs_bucket, bt.name))

    return ret
