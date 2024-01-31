# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for invoking the per project buildspec tool."""

from PB.recipes.chromeos.project_buildspec import ProjectBuildspecProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'cros_infra_config',
    'gobin',
]


PROPERTIES = ProjectBuildspecProperties

# See go/per-project-buildspecs for more context.


def RunSteps(api: RecipeApi, properties: ProjectBuildspecProperties):
  with api.bot_cost.build_cost_context():
    with api.step.nest('create program/project buildspec(s)'):
      cmd = ['project-buildspec']
      cmd += ['--buildspec', properties.buildspec]
      cmd += ['--projects', ','.join(properties.projects)]
      if not properties.dry_run:
        cmd += ['--push']

      api.gobin.call('manifest_doctor', cmd)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          ProjectBuildspecProperties(buildspec='buildspecs/foo/1.2.3.xml',
                                     projects=['galaxy/milkyway', 'foo/*'])),
      api.post_check(post_process.StepCommandContains,
                     'create program/project buildspec(s).run manifest_doctor',
                     [
                         '--buildspec',
                         'buildspecs/foo/1.2.3.xml',
                         '--projects',
                         'galaxy/milkyway,foo/*',
                         '--push',
                     ]), api.post_process(post_process.DropExpectation))
