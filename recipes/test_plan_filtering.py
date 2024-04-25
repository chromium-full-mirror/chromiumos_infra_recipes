# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Updates test plan rules to reflect new risk-based rules."""

# Test plans (as specified here:
# https://source.corp.google.com/chromeos_public/src/config/proto/chromiumos
# /config/api/test/plan/v1/plan.proto), define tests to run in terms lists of
# alternative devices and components; this gives us flexibility to adapt how we
# run test plans to accommodate current lab inventory and device availability.
# This recipe ingests those test plans, uses recent lab inventory information
# and materializes test plans not yet scheduled against specific devices and
# components.
#
# It does the following:
#   Clone config/config-internal repos.
#
#   Search for generated test plans.
#
#   Run `filter_test_plans_by_availability.py` and direct the results back next
#   to the source test plan.
#
#   Run `generate_test_plan_summary` on those plans.
#
#   Commit the resulting diff (if any) back to config-internal.

import os
from typing import List
from typing import Optional
from typing import Union

from PB.recipes.chromeos.test_plan_filtering import TestPlanFilteringProperties
from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

PROPERTIES = TestPlanFilteringProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_source',
    'gerrit',
    'repo',
    'git',
    'git_txn',
]


# Scripts
FIND_TESTS_PATH = \
    'infra/config/scripts/device_usage/get_test_plans_to_be_filtered.py'
FILTER_TESTS_BY_AVAILABILITY_PATH = \
    'infra/config/scripts/device_usage/filter_test_plans_by_availability.py'
GENERATE_TEST_PLAN_SUMMARY_PATH = \
    'src/config-internal/test/scripts/generate_test_plan_summary.py'

# Git Paths
CONFIG_PATH = 'src/config'
INFRA_CONFIG_PATH = 'infra/config'
CONFIG_INTERNAL_PATH = 'src/config-internal'
PAYLOAD_UTILS_PATH = os.path.join(CONFIG_PATH, 'payload_utils')
TEST_PLANS_PATH = 'test/plans'

# Cloud Credentials
CLOUD_CREDS_PATH = '/creds/service_accounts/service-account-chromeos.json'

PathLike = Union[str, Path]


def _generate_filter_test_output_file_path(api: RecipeApi,
                                           file_path: PathLike) -> str:
  """Make file path compliant with filter step's output.

  Effectively here we take the file path to a test plan and modify it to
  show it has been updated.
  Used by the filter step as an output file path.
  E.g.:
    "/base/uri/filename.jsonproto" => "/base/uri/filename.filtered.jsonproto"

  Args:
    api: Ubiquitous API object.
    file_path: The original file path to be used for modification.
  Returns:
    An updated file path with ".filtered.jsonproto" appended.
  """
  basename = api.path.basename(file_path)
  basename_without_jsonproto = basename[:-len('.jsonproto')]
  path_name = api.path.dirname(file_path)

  return api.path.join(
      path_name, '{}.filtered.jsonproto'.format(basename_without_jsonproto))


def _generate_test_plan_summary_file_path(api: RecipeApi,
                                          file_path: PathLike) -> str:
  """Make file path compliant with generate step's output.

  Here we take a file path and to a test plan and provide a new path where
  related generated test plans will live.
  Used by the generate step as an output file path.
  E.g.: "/base/uri/filename" => "/base/uri/test_plans"

  Args:
    api: Ubiquitous API object.
    file_path: The original file path to be used for modification.
  Returns:
    str: An updated file path with "/test_plans" appended.
  """
  path_name = api.path.dirname(file_path)

  return api.path.join(path_name, 'test_plans')


def _run_filter_command_and_commit(api: RecipeApi, input_file: PathLike,
                                   output_file: PathLike):
  """Run filter_test_plan_by_availability.sh

  Runs filter_test_plan_by_availability.sh on input_file,
  using output_file as output; then add the file to git.

  Args:
    api: Ubiquitous API object.
    input_file: Input file for filter_test_plan_by_availability.
    output_file: Output file for filter_test_plan_by_availability.
  """
  filter_test_script = api.cros_source.workspace_path.joinpath(
      FILTER_TESTS_BY_AVAILABILITY_PATH)

  filter_command = [
      'vpython3',
      filter_test_script,
      '--input',
      input_file,
      '--output',
      output_file,
  ]

  python_paths = []
  for dependency in [
      PAYLOAD_UTILS_PATH, INFRA_CONFIG_PATH, CONFIG_INTERNAL_PATH
  ]:
    python_paths.append('{}'.format(api.cros_source.workspace_path /
                                    dependency))

  with api.context(
      env={
          'GOOGLE_APPLICATION_CREDENTIALS': CLOUD_CREDS_PATH,
          'PYTHONPATH': ':'.join(python_paths)
      }):
    api.step('filter test plans by availability step', filter_command)

  api.git.add([output_file])


def _run_generate_command_and_commit(api: RecipeApi, input_file: PathLike,
                                     output_file: PathLike):
  """Run generate_test_plan_summary.py

  Runs generate_test_plan_summary.py on input_file,
  using output_file as output; then add the file to git.

  Args:
    api: Ubiquitous API object.
    input_file: Input File for generate_test_plan_summary.
    output_file: Output file for generate_test_plan_summary.
  """
  generate_test_plan_summary_script = api.cros_source.workspace_path.joinpath(
      GENERATE_TEST_PLAN_SUMMARY_PATH)

  generate_command = [
      generate_test_plan_summary_script,
      '--input',
      input_file,
      '--output',
      output_file,
  ]

  api.step('generate test plan summary step', ['vpython3'] + generate_command)

  api.git.add([output_file])


def _update_test_plans(api: RecipeApi, file_path: PathLike):
  """Run all update plan scripts.

  Runs both the filter and generate steps in order on the specified file_path.
  Files are added to git when done.

  Args:
    api: Ubiquitous API object.
    file_path: File path to run both steps on, representing a test_plan which
      must be updated.
  """
  # First we run filter for the file
  generated_file = _generate_filter_test_output_file_path(api, file_path)
  _run_filter_command_and_commit(api, input_file=file_path,
                                 output_file=generated_file)

  # Then we run generate for that filtered file
  generated_summary_file = _generate_test_plan_summary_file_path(
      api, file_path=generated_file)
  _run_generate_command_and_commit(api, input_file=generated_file,
                                   output_file=generated_summary_file)


def _find_test_plan_files(api: RecipeApi) -> List[str]:
  """Find all test plan files inside the repo folder

  Run the get_test_plans_to_be_filtered script, which finds all required
  test plan files. Splits the newline-delimited output into a list.

  Args:
    api: Ubiquitous API object.
  Returns:
    A compiled list of all test plan files.
  """
  find_tests_script = api.cros_source.workspace_path / FIND_TESTS_PATH

  find_command = [
      find_tests_script,
      '--repo',
      '{}'.format(api.context.cwd.join(TEST_PLANS_PATH)),
  ]

  step_result = api.step('find test plans', ['vpython3'] + find_command,
                         stdout=api.raw_io.output_text())

  return step_result.stdout.strip().splitlines()


def RunSteps(api: RecipeApi, _: TestPlanFilteringProperties):

  # BEGIN INTERNAL METHOD DEFINITIONS
  def _filter_all_test_plans() -> Optional[bool]:
    """Callback for git_txn.update_refs.

    Runs the filter steps and adds files to git and commits them if anything
    changed. Otherwise do nothing.

    Returns:
      False if nothing is to be changed. Otherwise None.
    """
    # Get all test plans which must be updated
    test_plan_files = _find_test_plan_files(api)

    # Updated test plans for all test plan files
    for test_plan_file in test_plan_files:
      _update_test_plans(api, file_path=test_plan_file)

    # If nothing got changed, don't push
    with api.step.nest('diffing to find changes'):
      changed_files = api.git.get_diff_files('HEAD')
      if not changed_files:
        return False  # abort transaction

    # commit files
    message = '''Updating test plans.
Cr-Build-Url: {}
Cr-Automation-Id: {}''' \
        .format(api.buildbucket.build_url(),
                'test_plan_filtering/filter')

    api.git.commit(message)
    return None

  # END INTERNAL METHOD DEFINITIONS

  api.cros_source.configure_builder()
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache(
        projects=[INFRA_CONFIG_PATH, CONFIG_PATH, CONFIG_INTERNAL_PATH])
    api.cros_source.checkout_tip_of_tree()

    config_internal = api.cros_source.workspace_path / CONFIG_INTERNAL_PATH

    # Update the repo atomically
    with api.context(cwd=config_internal):
      config_project_info = api.repo.project_info()
      api.git_txn.update_ref(config_project_info.remote, _filter_all_test_plans,
                             ref=api.git.remote_head(), automerge=True)


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic',
      # Mocking to make it seem there are 3 star files
      api.step_data(
          'update ref.gerrit transaction.find test plans',
          stdout=api.raw_io.output_text('\n'.join([
              '[START_DIR]/base1/file1.jsonproto',
              '[START_DIR]/base2/file2.jsonproto',
              '[START_DIR]/base3/file3.jsonproto'
          ]))),
      # Mocking git diff step to show differences so transaction is called
      api.step_data(
          'update ref.gerrit transaction.diffing to find changes.git diff',
          stdout=api.raw_io.output_text('changes')),
      api.post_check(post_process.MustRun, 'update ref.gerrit transaction.'
                     'git push'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'no-changes-produced-in-diff-causes-no-push',
      # Mocking to make it seem there are 3 star files
      api.step_data(
          'update ref.gerrit transaction.find test plans',
          stdout=api.raw_io.output_text('\n'.join([
              '[START_DIR]/base1/file1.jsonproto',
              '[START_DIR]/base2/file2.jsonproto',
              '[START_DIR]/base3/file3.jsonproto'
          ]))),
      # Mocking git diff step to show no differences so transaction cancelled
      api.step_data(
          'update ref.gerrit transaction.diffing to find changes.git diff',
          stdout=api.raw_io.output_text('')),
      api.post_check(post_process.DoesNotRun, 'update ref.gerrit transaction.'
                     'git push'),
  )
