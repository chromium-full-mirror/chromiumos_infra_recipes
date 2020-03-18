# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class RepoTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the repo module."""

  def local_manifest_step_test_data(self):
    """Returns test data to simulate a local manifest."""
    test_manifest = """
<manifest>
  <remote name="cros-internal"
          fetch="https://chrome-internal.googlesource.com"
          review="https://chrome-internal-review.googlesource.com" />
  <project name="chromeos/private-repo1"
     path="src/private-repo1"
     remote="cros-internal" />
</manifest>
    """

    return self.m.gitiles.make_encoded_file(test_manifest)
