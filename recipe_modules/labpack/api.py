# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.labpack.result_map import new_result_map, add_assertion_to_map


class LabpackCommand(recipe_api.RecipeApi):
  """Labpack command is a singleton whose methods invoke the labpack CIPD executable"""

  def get_cipd_path(self):
    """Get the path of the cipd package.

    Get the location of a path inside cleanup, which is guaranteed to be
    cleaned between runs.

    See documentation below for details:

    https://chromium.googlesource.com/infra/luci/recipes-py/+/HEAD/README.recipes.md#recipe_modules-path
    """
    return self.m.path['cleanup'].join('cipd', 'labpack')

  def ensure_labpack(self):
    """Ensure labpack ensures that labpack exists.

    We create a cipd package area inside the cleanup directory,
    add labpack to the manifest file, and then ensure the resulting
    manifest.

    Args: No arguments

    Returns: Dictionary
    """
    out = new_result_map()
    # Add labpack to the current cipd package.
    with self.m.step.nest('ensure labpack'):
      pkgs = self.m.cipd.EnsureFile()
      # TODO(gregorynisbet): Consider modifying this to be overridable as a recipe input.
      pkgs.add_package('chromiumos/infra/labpack/${platform}', 'prod')
      self.m.cipd.ensure(self.get_cipd_path(), pkgs)

      # So, we have to have a mock call here. Let me tell you why.
      # The intended consumer of this module is the recipe script
      # test_runner.py. test_runner.py is itself a script and not a
      # module, so we don't get the opportunity to run mock_add_file
      # before the test cases run, since the test cases are just fake
      # requests that get yielded one at a time within GenTests. I
      # don't want to change the tests to test_runner.py substantially
      # just to allow it to use this module.
      #
      # The cipd recipe module itself does not emulate the behavior of
      # the cipd executable very deeply when run in test mode. In
      # particular, it does not cause paths that would be populated as
      # a result of ensuring a manifest file to spring into existence.
      # I want this recipe to be as easy to debug as possible, so I'm
      # checking for the presence of the labpack executable after we
      # perform an action that should put it there. In order to have
      # that behavior in prod, though, I need a way to defuse the check
      # when testing. This means always running mock_add_file, which is
      # a no-op in prod.
      self.m.path.mock_add_file(self.get_cipd_path().join('labpack'))
    # Just to confirm that everything is functioning as expected,
    # check to see that the labpack executable is available at
    #
    # 1) [START_DIR]/cipd/labpack/labpack
    # 2) [START_DIR]\cipd\labpack\labpack.exe
    #
    with self.m.step.nest('confirm labpack is installed'):
      paths = [
          self.get_cipd_path().join('labpack'),
          self.get_cipd_path().join('labpack.exe'),
      ]
      tally = sum(self.m.path.exists(path) for path in paths)
      add_assertion_to_map(out, tally,
                           "labpack does not exist at paths {}".format(paths))
      add_assertion_to_map(
          out, tally, "labpack exists at exaclty one path in {}".format(paths))
    return out
