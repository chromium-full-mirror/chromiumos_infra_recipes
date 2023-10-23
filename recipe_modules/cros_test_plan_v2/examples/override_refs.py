# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import StarlarkPackage

TemplateParameters = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile.TemplateParameters

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_test_plan_v2',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_test_plan_v2.validate(api.path.mkdtemp())

  api.cros_test_plan_v2.generate_hw_test_plans([
      StarlarkPackage(root='root1', main='example1.star',
                      template_parameters=TemplateParameters()),
      StarlarkPackage(root='root2', main='example2.star',
                      template_parameters=TemplateParameters()),
  ])


def GenTests(api):

  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2': {
                  'platform_test_plan_docker_image': 'mytestplandocker',
                  'platform_test_plan_docker_tag': 'mydockertag',
              }
          }),
      api.post_process(
          post_process.StepCommandEquals,
          'generate hw test plans.ensure docker image.docker pull mytestplandocker:mydockertag',
          [
              'docker', '--config', '[CLEANUP]/.docker', 'pull',
              'us-docker.pkg.dev/cros-registry/test-services/mytestplandocker:mydockertag'
          ]),
      api.post_process(post_process.DropExpectation),
  )
