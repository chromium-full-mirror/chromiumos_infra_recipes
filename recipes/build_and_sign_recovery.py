# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build and sign recovery kernel images."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_source',
    'git',
]


def RunSteps(api: RecipeApi):
  with api.cros_source.checkout_overlays_context():
    api.cros_source.configure_builder(api.buildbucket.gitiles_commit)

    # Signing uses config for the base target. Remove prefix if present.
    target = api.build_menu.build_target.name.split('android-')[-1]

    # TODO(b/371248376): Remove when we can create our own recovery image.
    # For now, just get the image from the android prebuild repo.
    checkout = api.path.mkdtemp()
    with api.context(cwd=checkout):
      api.git.clone(
          f'https://googleplex-android.googlesource.com/device/google/desktop/{target}-kernels',
          depth=1)

      recovery_local_path = api.path.join(
          api.path.mkdtemp(prefix='recovery'), 'vmlinuz.image')

      # copy the file in.
      api.file.copy('copy prebuild recovery image into temp dir',
                    api.path.join(checkout, '6.6', 'recovery', 'vmlinuz.image'),
                    recovery_local_path)

    # TODO(b/371248376): Sign recovery and upload to GS and android repo.


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'success',
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/brya-kernels'
      ]),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_process(post_process.DropExpectation),
      build_target='android-brya',
  )
