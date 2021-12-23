# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for providing release related utility functions."""

from recipe_engine import recipe_api


class CrosReleaseUtilApi(recipe_api.RecipeApi):

  def release_builder_name(self, build_target, branch=None, staging=False):
    """Determine the Rubik child builder name for the given build_target.

      Args:
        build_target (string): name of the build target, e.g. zork or kevin-kernelnext
        branch (string): optional, branch we're on.
        staging (string): optional, whether or not we're in staging.

      Return:
        The Rubik child builder, e.g. zork-release-main.
      """
    staging_prefix = 'staging-' if (staging or
                                    self.m.cros_infra_config.is_staging) else ''
    branch_suffix = branch or self.m.cros_source.manifest_branch
    if branch_suffix.startswith("release-"):
      branch_suffix = branch_suffix[len("release-"):]
    if not branch_suffix:
      branch_suffix = "main"
    target_release_builder_name = "{}{}-release-{}".format(
        staging_prefix, build_target, branch_suffix)
    return target_release_builder_name
