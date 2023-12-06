# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Various methods for debugging recipes builds."""

import random

from recipe_engine import recipe_api

# Max out the total amount of time a bot can sleep to 4 hours, for safety.
TOTAL_MAX_TIMEOUT = 4 * 60 * 60


class CrosDebugApi(recipe_api.RecipeApi):
  """A module to be used for debugging builders."""

  def pause_and_wait_for_signal(self, timeout=10 * 60,
                                override_led_launch_only_staging=False,
                                test_location_override=None):
    """Halt the builder and wait for a signal to continue.

    This method is meant to be used to debug a builder. The thought here is that
    we've exhausted all other possibilities and our course of action is to try
    to run the recipe and then ssh into the bot.

    To use this, call the method right where you want the builder to halt. When
    you run the build, it will halt there and wait. If you look at the builder's
    step output, it should tell you that it is sleeping for a time span, and
    specify a sentinel file to create when you are ready to release the bot and
    continue the execution.

    By default, this will only work for a led launch against a staging builder,
    but if you are determined to do it either against a prod builder or merge
    through the code and run in staging, you can specify the override flag.

    Args:
      timeout (int): how long to wait for a continue signal, in seconds.
        Defaults to 10 minutes.
      override_led_launch_only_staging (bool): override flag to allow outside
        led and/or outside of staging.
      test_location_override (Path): by default this method creates its own temp
        location to look for the `resume` file, but for tests the location can
        be passed in with this property for ease of verification.
    """
    with self.m.step.nest('debug builder steps') as presentation:
      # Step 1. Safety checks.
      if (not self.m.cros_infra_config.is_staging or self.m.buildbucket.build.id
          != 0) and not override_led_launch_only_staging:
        # Emit that we're skipping this debug step.
        presentation.step_text = 'Skipping debug steps as this is not a led launch or it is running outside of staging. Please either remove `cros_debug` from this recipe, or pass in the override flag if you really must run this this way.'
        presentation.status = self.m.step.INFRA_FAILURE
        return
      if timeout > TOTAL_MAX_TIMEOUT:
        presentation.step_text = 'Timeout specified is outside valid range, capping at 4 hours.'
        timeout = TOTAL_MAX_TIMEOUT

      # Step 2. Create sentinel file to watch.
      path = test_location_override or self.m.path.mkdtemp()
      with self.m.context(cwd=path):
        with self.m.step.nest('set up file to watch') as pres:
          file_to_watch = '{}/resume'.format(path)
          pres.step_text = 'Watching for file to appear to resume build. To resume, run `touch {}` on the bot'.format(
              file_to_watch)

        # Step 3. Poll for the file's existence (or wait for the timeout).
        with self.m.step.nest('waiting for file to appear') as pres:
          start_time = self.m.time.utcnow()
          while (self.m.time.utcnow() - start_time).total_seconds() < timeout:
            if self.m.path.exists(file_to_watch):
              pres.step_text = 'found file, done sleeping'
              break

            self.m.time.sleep(5)

        # Step 4. If the file exists, delete it to not pollute the next run.
        with self.m.step.nest('clean up'):
          if self.m.path.exists(file_to_watch):
            self.m.easy.stdout_step('remove resume file', ['rm', file_to_watch],
                                    infra_step=True)

  def patch_chromite_head(self, cl_number: int, patchset: int = 1):
    """Patch the chromite-HEAD checkout with the given CL.

    Intended for use in a led job. To use this, call this function at the end
    of cros_build_api.reset_checkout.

    Args:
      cl_number: Number of the (chromite) CL, e.g. 5095955.
      patchset: Patchset of the change.
    """
    self.m.step(
        f'fetch crrev.com/c/{cl_number}',
        f'git fetch https://chromium.googlesource.com/chromiumos/chromite refs/changes/{cl_number % 100}/{cl_number}/{patchset}'
        .split())
    self.m.step(
        f'checkout crrev.com/c/{cl_number}',
        f'git checkout -b change-{cl_number}{random.randint(1, 10000)} FETCH_HEAD'
        .split())
