# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for using the `dirmd` tool."""

from recipe_engine import recipe_api



class DirmdApi(recipe_api.RecipeApi):
  """A module for using the dirmd tool."""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._cipd_package = properties.dirmd_cipd_package or 'infra/tools/dirmd/${platform}'
    self._cipd_ref = properties.dirmd_cipd_ref or 'latest'
    self._dirmd_path = None

  def _ensure_dirmd(self):
    """Ensure the dirmd tool is installed with CIPD."""
    if self._dirmd_path:
      return

    with self.m.step.nest('ensure dirmd'):
      with self.m.context(infra_steps=True):
        # Install into a directory specific to dirmd, to avoid collisions with
        # other CIPD installations.
        cipd_dir = self.m.path.start_dir / 'cipd_dirmd'

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package, self._cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._dirmd_path = cipd_dir / 'dirmd'

  def validate_dir(self, directory: str) -> None:
    """Find and validate all DIR_METADATA files in a directory.

    Raises a StepFailure if validation fails, otherwise returns None.

    Args:
      directory: Path to a directory to validate. Note that this should be a
          directory, not a DIR_METADATA file. Any DIR_METADATA files in a
          subdirectory of directory will also be validated.
    """
    with self.m.step.nest('dirmd validate {}'.format(directory)) as pres:
      self._ensure_dirmd()
      # Use the `find` command because the `file.glob_paths` function infinite
      # loops if there is a symlink cycle in a repo.
      dirmd_paths = self.m.easy.stdout_step(
          'find DIR_METADATA files',
          ['find', directory, '-name', 'DIR_METADATA'
          ]).decode().strip().split('\n')

      # Calling `split('\n')` on any empty string will produce the list `['']`.
      # So check that there is at least one non-empty string in the list.
      if not any(p for p in dirmd_paths):
        pres.step_summary_text = 'No DIR_METADATA files found'
        return

      self.m.step('dirmd validate',
                  [self._dirmd_path, 'validate'] + dirmd_paths)
