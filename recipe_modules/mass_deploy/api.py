# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for triggering the mass deploy builder"""

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class MassDeployApi(recipe_api.RecipeApi):

  @staticmethod
  def _select_stable_recovery_image(signing_metadata):
    """Returns just the metadata for the signed stable recovery image, or None."""
    for metadata in signing_metadata.values():
      if (metadata['channel'] == 'stable' and metadata['type'] == 'recovery'):
        return metadata

    return None

  def _select_zip(self, build_metadata):
    """Finds the zipped version of the signed image. Insists there be only 1."""
    image_zip = [
        out for out in build_metadata['outputs'] if out.endswith('.zip')
    ]
    # Validate that there's precisely one zip that we've picked up.
    num_zips = len(image_zip)
    if num_zips != 1:
      raise StepFailure(f'{num_zips} output zips found: {image_zip}')

    return image_zip[0]

  def run_mass_deploy_generation(self, signing_metadata):
    """Run the generation of the mass deployment image, but don't wait for it.

    This assumes signed builds have already been generated.
    """
    # We only build mass deploy images for stable.
    with self.m.step.nest('generate mass deploy builds'):
      with self.m.step.nest('only run on stable builds') as presentation:
        stable_build_metadata = self._select_stable_recovery_image(
            signing_metadata)
        if stable_build_metadata is None:
          presentation.step_text = 'no stable build, stopping'
          return

      with self.m.step.nest('determine builder settings'):
        release_milestone = stable_build_metadata['version']['milestone']
        release_directory = stable_build_metadata['release_directory']
        input_zip = self._select_zip(stable_build_metadata)
        properties = {
            'input_image': f'{release_directory}/{input_zip}',
            'milestone': release_milestone
        }

        # Match names as constructed in infra/config/release/main.star.
        builder_prefix = 'staging-' if self.m.build_menu.is_staging else ''
        builder = builder_prefix + 'release-mass-deploy'

      with self.m.step.nest('schedule mass deploy build') as presentation:
        request = self.m.buildbucket.schedule_request(
            builder=builder,
            properties=properties,
            can_outlive_parent=True,
            tags=self.m.buildbucket.tags(
                parent_buildbucket_id=str(self.m.buildbucket.build.id)),
        )
        self.m.buildbucket.schedule([request])

        presentation.step_summary_text = f'scheduled {builder}'
