# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.chromiumos.test.api.test_suite import TestSuite
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import StarlarkPackage

TemplateParameters = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile.TemplateParameters
TestCaseTagCriteria = TestSuite.TestCaseTagCriteria

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  starlark_packages = [
      StarlarkPackage(
          root='root1',
          main='example1.star',
          template_parameters=TemplateParameters(
              suite_name='catA',
              tag_criteria=TestCaseTagCriteria(
                  tags=['group:catA'],
                  tag_excludes=['informational'],
              ),
          ),
      ),
      StarlarkPackage(root='root2', main='example2.star',
                      template_parameters=TemplateParameters()),
  ]

  build_1 = build_pb2.Build()
  build_1.builder.builder = 'target1-cq'
  build_1.input.properties['build_target'] = {'name': 'target1'}
  build_2 = build_pb2.Build()
  build_2.builder.builder = 'target2-cq'
  build_2.input.properties['build_target'] = {'name': 'target2'}
  # This builder will be excluded from the results because its name contains
  # "-bazel-".
  build_3 = build_pb2.Build()
  build_3.builder.builder = 'target1-bazel-cq'
  build_3.input.properties['build_target'] = {'name': 'target1'}

  api.assertions.assertCountEqual(
      api.cros_test_plan_v2.get_testable_builders(starlark_packages,
                                                  [build_1, build_2, build_3]),
      ['target1-cq', 'target2-cq'])


def GenTests(api):
  build_1 = build_pb2.Build()
  build_1.builder.builder = 'target1-cq'
  build_1.input.properties['build_target'] = {'name': 'target1'}
  build_2 = build_pb2.Build()
  build_2.builder.builder = 'target2-cq'
  build_2.input.properties['build_target'] = {'name': 'target2'}

  yield api.test(
      'basic',
      api.post_process(
          post_process.StepCommandContains,
          'get testable builders.write builds.jsonl',
          [
              'copy',
              ('{"builder": {"builder": "target1-cq"},"input": {"properties": {"build_target": {"name": "target1"}}}}\n'
               '{"builder": {"builder": "target2-cq"},"input": {"properties": {"build_target": {"name": "target2"}}}}\n'
               '{"builder": {"builder": "target1-bazel-cq"},"input": {"properties": {"build_target": {"name": "target1"}}}}'
              ),
              '[CLEANUP]/tmp_tmp_1/builds.jsonl',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'get testable builders.docker run',
          [
              '--image',
              'us-docker.pkg.dev/cros-registry/test-services/testplan:prod',
              '--dir-map',
              '[CLEANUP]/tmp_tmp_1',
              '/input',
              '--',
              'get-testable',
              '-plan',
              '/input/root1/example1.star',
              '-plan',
              '/input/root2/example2.star',
              '-templateparameter',
              '/input/root1/example1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-builds',
              '/input/builds.jsonl',
              '-builderconfigs',
              '/input/builder_configs.binaryproto',
              '-buildmetadata',
              '/input/build_metadata.jsonproto',
              '-configbundlelist',
              '/input/configs.jsonproto',
              '-dutattributes',
              '/input/dut_attributes.jsonproto',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-use-infra-go-bin-experiment',
      api.buildbucket.try_build(
          project='chromeos',
          bucket='cq',
          builder='cq-orchestrator',
          experiments=['chromeos.cros_test_plan_v2.use_infra_gobin'],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'get testable builders.write builds.jsonl',
          [
              'copy',
              ('{"builder": {"builder": "target1-cq"},"input": {"properties": {"build_target": {"name": "target1"}}}}\n'
               '{"builder": {"builder": "target2-cq"},"input": {"properties": {"build_target": {"name": "target2"}}}}\n'
               '{"builder": {"builder": "target1-bazel-cq"},"input": {"properties": {"build_target": {"name": "target1"}}}}'
              ),
              '[CLEANUP]/tmp_tmp_1/builds.jsonl',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'get testable builders.validate infra go bin.test_plan get-testable',
          [
              '[START_DIR]/cipd/test_plan/test_plan',
              'get-testable',
              '-plan',
              'root1/example1.star',
              '-plan',
              'root2/example2.star',
              '-templateparameter',
              'root1/example1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-builds',
              '[CLEANUP]/tmp_tmp_1/builds.jsonl',
              '-builderconfigs',
              '[CLEANUP]/tmp_tmp_1/builder_configs.binaryproto',
              '-buildmetadata',
              '[CLEANUP]/tmp_tmp_1/build_metadata.jsonproto',
              '-configbundlelist',
              '[CLEANUP]/tmp_tmp_1/configs.jsonproto',
              '-dutattributes',
              '[CLEANUP]/tmp_tmp_1/dut_attributes.jsonproto',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-use-infra-go-bin-experiment-different-responses',
      api.buildbucket.try_build(
          project='chromeos',
          bucket='cq',
          builder='cq-orchestrator',
          experiments=['chromeos.cros_test_plan_v2.use_infra_gobin'],
      ),
      api.override_step_data(
          'get testable builders.validate infra go bin.test_plan get-testable',
          api.raw_io.output(
              'other-builder1 other-builder2',
          ),
      ),
      api.post_process(
          post_process.StepCommandContains,
          'get testable builders.write builds.jsonl',
          [
              'copy',
              ('{"builder": {"builder": "target1-cq"},"input": {"properties": {"build_target": {"name": "target1"}}}}\n'
               '{"builder": {"builder": "target2-cq"},"input": {"properties": {"build_target": {"name": "target2"}}}}\n'
               '{"builder": {"builder": "target1-bazel-cq"},"input": {"properties": {"build_target": {"name": "target1"}}}}'
              ),
              '[CLEANUP]/tmp_tmp_1/builds.jsonl',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'get testable builders.validate infra go bin.test_plan get-testable',
          [
              '[START_DIR]/cipd/test_plan/test_plan',
              'get-testable',
              '-plan',
              'root1/example1.star',
              '-plan',
              'root2/example2.star',
              '-templateparameter',
              'root1/example1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-builds',
              '[CLEANUP]/tmp_tmp_1/builds.jsonl',
              '-builderconfigs',
              '[CLEANUP]/tmp_tmp_1/builder_configs.binaryproto',
              '-buildmetadata',
              '[CLEANUP]/tmp_tmp_1/build_metadata.jsonproto',
              '-configbundlelist',
              '[CLEANUP]/tmp_tmp_1/configs.jsonproto',
              '-dutattributes',
              '[CLEANUP]/tmp_tmp_1/dut_attributes.jsonproto',
          ],
      ),
      api.post_process(post_process.StepTextEquals,
                       'get testable builders.validate infra go bin',
                       'responses were different'),
      api.post_process(post_process.PropertyEquals,
                       'test_plan_infra_gobin_get_testable_responses_match',
                       False),
      api.post_process(post_process.DropExpectation),
  )
