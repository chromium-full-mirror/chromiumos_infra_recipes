# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosArtifactsTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_artifacts module."""

  # Number of seconds to wait on gsutil rsync.
  gsutil_timeout_seconds = 15 * 60

  @recipe_test_api.mod_test_data
  @staticmethod
  def set_prepare_pointless(artifact_pointless):
    """Remove the given endpoints from the API.

    Args:
      artifact_pointless (bool): Whether the prepare endpoint should return
        POINTLESS.

    Returns:
      (mod_test_data) to pass to api.test.
    """
    return artifact_pointless
