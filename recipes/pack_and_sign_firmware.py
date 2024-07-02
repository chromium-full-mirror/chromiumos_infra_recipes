# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Pack and sign standalone firmware shellball."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_release',
]


def RunSteps(api: RecipeApi):
  # TODO(b/350787871): Remove when we can call pack_firmware to create our own shellball.
  shellball_local_path = api.path.join(
      api.path.mkdtemp(prefix='shellball'), 'chromeos-firmwareupdate')
  api.gsutil.download('chromeos-throw-away-bucket/bshai',
                      'chromeos-firmwareupdate', shellball_local_path,
                      name='download test shellball')

  # TODO(b/350787871): Sign shellball and upload to GS.


def GenTests(api: RecipeTestApi):
  yield api.test(
      'success',
      api.post_check(post_process.MustRun, 'gsutil download test shellball'),
      api.post_process(post_process.DropExpectation))
