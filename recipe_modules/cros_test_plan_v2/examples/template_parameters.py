# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.test.api.test_suite import TestSuite
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import StarlarkPackage


TemplateParameters = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile.TemplateParameters
TestCaseTagCriteria = TestSuite.TestCaseTagCriteria

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]



def RunSteps(api):
  generate_test_plan_request = GenerateTestPlanRequest(
      buildbucket_protos=[ProtoBytes(serialized_proto=b'abc123')],
  )
  api.cros_test_plan_v2.generate_hw_test_plans(
      [
          StarlarkPackage(
              root='root',
              main='templatedplan1.star',
              template_parameters=TemplateParameters(
                  suite_name='catA',
                  tag_criteria=TestCaseTagCriteria(
                      tags=['group:catA'],
                      tag_excludes=['informational'],
                  ),
              ),
          ),
      ],
      generate_test_plan_request,
  )

  api.cros_test_plan_v2.generate_hw_test_plans(
      [
          StarlarkPackage(
              root='root',
              main='templatedplan1.star',
              template_parameters=TemplateParameters(
                  suite_name='catA',
                  tag_criteria=TestCaseTagCriteria(
                      tags=['group:catA'],
                      tag_excludes=['informational'],
                  ),
              ),
          ),
          StarlarkPackage(
              root='root',
              main='templatedplan1.star',
              template_parameters=TemplateParameters(
                  suite_name='catB',
                  tag_criteria=TestCaseTagCriteria(
                      tags=['group:catB'],
                      tag_excludes=['informational'],
                  ),
              ),
          ),
      ],
      generate_test_plan_request,
  )

  api.cros_test_plan_v2.generate_hw_test_plans(
      [
          StarlarkPackage(
              root='root',
              main='templatedplan1.star',
              template_parameters=TemplateParameters(
                  suite_name='catA',
                  tag_criteria=TestCaseTagCriteria(
                      tags=['group:catA'],
                      tag_excludes=['informational'],
                  ),
              ),
          ),
          StarlarkPackage(
              root='root',
              main='templatedplan2.star',
              template_parameters=TemplateParameters(
                  suite_name='catA',
                  tag_criteria=TestCaseTagCriteria(
                      tags=['group:catA'],
                      tag_excludes=['informational'],
                  ),
              ),
          ),
      ],
      generate_test_plan_request,
  )


def GenTests(api):

  yield api.test(
      'basic',
      api.buildbucket.try_build(
          project='chromeos',
          bucket='cq',
          builder='cq-orchestrator',
      ),
      api.properties(
          **{'$chromeos/cros_test_plan_v2': {
              'generate_ctpv1_format': True
          }}),
      # First call passes a single file and TemplateParameters, expect 1 -plan
      # and 1 -templateparameter.
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans.test_plan generate',
          [
              '-plan',
              'root/templatedplan1.star',
              '-templateparameter',
              'root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
          ],
      ),
      # Second call passes the same file with two different TemplateParameters,
      # expect 1 -plan and 2 -templateparameter.
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans (2).test_plan generate',
          [
              '-plan', 'root/templatedplan1.star', '-templateparameter',
              'root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-templateparameter',
              'root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catB"],"tagExcludes": ["informational"]},"suiteName": "catB"}\''
          ],
      ),
      # Third call passes two different files with the same TemplateParameters,
      # expect 2 -plan and 2 -templateparameter.
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans (3).test_plan generate',
          [
              '-plan', 'root/templatedplan1.star', '-plan',
              'root/templatedplan2.star', '-templateparameter',
              'root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-templateparameter',
              'root/templatedplan2.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\''
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
