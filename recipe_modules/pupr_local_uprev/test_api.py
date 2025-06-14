# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class PuprLocalUprevTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the pupr_local_uprev module."""

  @property
  def sdk_project_infos_step_data(self) -> recipe_test_api.TestData:
    """Return test step data for fetching project infos for SDK uprevs."""
    return self.m.repo.project_infos_test_data([{
        'project': 'chromiumos/overlays/board-overlays',
        'path': 'src/overlays',
        'remote': 'cros',
        'rrev': 'refs/heads/main',
    }, {
        'project': 'chromiumos/overlays-chromiumos-overlay',
        'path': 'src/third_paty/chromiumos-overlay',
        'remote': 'cros',
        'rrev': 'refs/heads/main',
    }])
