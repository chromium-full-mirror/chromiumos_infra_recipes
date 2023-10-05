# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.test.api.test_suite import TestSuite
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import StarlarkPackage

TemplateParameters = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile.TemplateParameters
TestCaseTagCriteria = TestSuite.TestCaseTagCriteria

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_test_plan_v2.generate_hw_test_plans([
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
  ])

  api.cros_test_plan_v2.generate_hw_test_plans([
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
  ])

  api.cros_test_plan_v2.generate_hw_test_plans([
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
  ])


def GenTests(api):

  yield api.test(
      'basic',
      # First call passes a single file and TemplateParameters, expect 1 -plan
      # and 1 -templateparameter.
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans.docker run',
          [
              '-plan',
              '/input/root/templatedplan1.star',
              '-templateparameter',
              '/input/root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
          ],
      ),
      # Second call passes the same file with two different TemplateParameters,
      # expect 1 -plan and 2 -templateparameter.
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans (2).docker run',
          [
              '-plan', '/input/root/templatedplan1.star', '-templateparameter',
              '/input/root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-templateparameter',
              '/input/root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catB"],"tagExcludes": ["informational"]},"suiteName": "catB"}\''
          ],
      ),
      # Third call passes two different files with the same TemplateParameters,
      # expect 2 -plan and 2 -templateparameter.
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans (3).docker run',
          [
              '-plan', '/input/root/templatedplan1.star', '-plan',
              '/input/root/templatedplan2.star', '-templateparameter',
              '/input/root/templatedplan1.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\'',
              '-templateparameter',
              '/input/root/templatedplan2.star:\'{"tagCriteria": {"tags": ["group:catA"],"tagExcludes": ["informational"]},"suiteName": "catA"}\''
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
