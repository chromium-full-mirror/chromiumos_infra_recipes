# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for triggering the mass deploy builder"""

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class MassDeployApi(recipe_api.RecipeApi):

  @staticmethod
  def _select_signed_recovery_images(signing_metadata):
    """Returns just the metadata for the signed recovery images.

    Only LTS mass deploy images are distributed to end users, but build mass
    deploy images for stable (and LTC) as well, so we can catch breakages in
    mass deploy image generation closer to when they occur.

    If no images we want to build are found, returns an empty list.
    """
    massdeploy_channels = ('ltc', 'lts', 'stable')
    result = []

    for metadata in signing_metadata.values():
      if (metadata['channel'] in massdeploy_channels and
          metadata['type'] == 'recovery'):
        result.append(metadata)

    return result

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

  def _plan_mass_deploy_builds(self, builds_metadata):
    """Return a list of (builder, properties) pairs, one for each input metadata

    `builder` is the name of a builder to run
    `properties` is a dict of the input properties to that builder
    """
    result = []

    for build in builds_metadata:
      release_milestone = build['version']['milestone']
      release_directory = build['release_directory']
      input_zip = self._select_zip(build)
      properties = {
          'input_image': f'{release_directory}/{input_zip}',
          'milestone': release_milestone
      }

      # Match names as constructed in infra/config/release/main.star.
      builder_prefix = 'staging-' if self.m.build_menu.is_staging else ''
      builder = builder_prefix + 'release-mass-deploy'

      result.append((builder, properties))

    return result

  def run_mass_deploy_generation(self, signing_metadata):
    """Run the generation of the mass deployment image, but don't wait for it.

    This assumes signed builds have already been generated.
    """
    with self.m.step.nest('generate mass deploy builds'):
      with self.m.step.nest(
          'only run on LTC, LTS or stable builds') as presentation:
        signed_builds_metadata = self._select_signed_recovery_images(
            signing_metadata)
        if not signed_builds_metadata:
          presentation.step_text = 'no LTC, LTS or stable build, stopping'
          return

      with self.m.step.nest('determine builder settings'):
        builds_to_run = self._plan_mass_deploy_builds(signed_builds_metadata)

      with self.m.step.nest('schedule mass deploy build(s)') as presentation:
        assert len(builds_to_run) > 0

        for builder, properties in builds_to_run:
          request = self.m.buildbucket.schedule_request(
              builder=builder,
              properties=properties,
              can_outlive_parent=True,
              tags=self.m.buildbucket.tags(
                  parent_buildbucket_id=str(self.m.buildbucket.build.id)),
          )
          self.m.buildbucket.schedule([request])
