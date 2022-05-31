# -*- coding: utf-8 -*-

# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf.json_format import MessageToDict

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation


class CrosLkgmApi(recipe_api.RecipeApi):
  """A module to handle the LGKM process and other interactions between the
    Release & Public builders."""

  def __init__(self, *args, **kwargs):
    super(CrosLkgmApi, self).__init__(*args, **kwargs)

  def schedule_public_build(self):
    """Schedules a public build.

    Returns: (Build) The scheduled build.
    """
    with self.m.step.nest('schedule public build'):
      config = self.m.cros_infra_config.config
      if not config:
        raise StepFailure(
            'could not find builder config, needed to determine branch')
      branch = config.orchestrator.gitiles_commit.ref[len('refs/heads/'):]

      is_staging = self.m.cros_infra_config.is_staging
      staging_prefix = 'staging-' if is_staging else ''
      public_orch_name = '{}public-{}-orchestrator'.format(
          staging_prefix, branch)

      buildspec_location = self.m.cros_release.releasespec.manifest_gs_path
      # We want to pass the public buildspec to the public builder.
      buildspec_location = buildspec_location.replace(
          'chromeos-manifest-versions', 'chromiumos-manifest-versions')

      request = self.m.buildbucket.schedule_request(
          bucket='staging' if is_staging else 'release',
          builder=public_orch_name,
          properties={
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path=buildspec_location))),
          },
          can_outlive_parent=True,
          tags=self.m.buildbucket.tags(
              parent_buildbucket_id=str(self.m.buildbucket.build.id)),
      )
      builds = self.m.buildbucket.schedule([request],
                                           step_name='running public builder')
      self._public_builder = builds[0]
      return self._public_builder
