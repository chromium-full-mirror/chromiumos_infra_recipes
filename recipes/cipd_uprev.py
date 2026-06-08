# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for upreving cipd packages."""

from typing import Generator

from PB.recipes.chromeos import cipd_uprev
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'deferrals',
    'golucibin',
]


PROPERTIES = cipd_uprev.Properties

_CI_RELEASE_VERSION_TAG = 'ci_release_version'


def validate(api: RecipeApi, instruction: cipd_uprev.Instruction) -> None:
  """Validate instructions for uprevving a specific package.

  Args:
    * instruction (cipd_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
  Raises:
    A ValueError if validation fails.
  """
  with api.step.nest('validate package instructions'):
    if not instruction.ref:
      raise StepFailure('No ref to update for package %s' %
                        instruction.package_name)
    if not instruction.version:
      raise StepFailure('No new version provided for package %s' %
                        instruction.package_name)


def get_current_instance(
    api: RecipeApi,
    instruction: cipd_uprev.Instruction) -> cipd_uprev.PackageInstance:
  """Get the current version of the ref.

  Args:
    * instruction (cipd_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
  Returns:
    cipd_uprev.PackageInstance
  Raises:
    A StepFailure if the CIPD tool call fails.
  """
  with api.step.nest(
      'get instance ID of package "%s" currently tagged with ref "%s"' %
      (instruction.package_name, instruction.ref)):
    try:
      instance_id = api.cipd.describe(package_name=instruction.package_name,
                                      version=instruction.ref).pin.instance_id
    except api.cipd.Error as e:
      if 'no such ref' in str(e):
        return cipd_uprev.PackageInstance(package_name=instruction.package_name,
                                          id='')
      raise
    return cipd_uprev.PackageInstance(package_name=instruction.package_name,
                                      id=instance_id)


def uprev_package(api: RecipeApi, instruction: cipd_uprev.Instruction,
                  package_tags=None) -> cipd_uprev.PackageInstance:
  """Change CIPD ref of a package according to the instructions.

  Args:
    * instruction (cipd_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
    * package_tags: Tags to add to the package.
  Returns:
    cipd_uprev.PackageInstance
  Raises:
    A StepFailure if the CIPD tool call fails.
  """
  package_tags = package_tags or {}
  with api.step.nest(
      'apply the "%s" ref of the "%s" package to "%s"' %
      (instruction.ref, instruction.package_name, instruction.version)) as pres:
    for tag_key, tag_value in package_tags.items():
      try:
        api.cipd.set_tag(instruction.package_name, instruction.version,
                         {tag_key: tag_value})
      except Exception as e:
        pres.step_text = 'Failed to set cipd tag. Check the stdout for the step for errors.'
        # We don't want an infra failure, so turn it into a StepFailure.
        raise StepFailure(
            'Failed to set cipd tag. Check the stdout for the step for errors.'
        ) from e
    instance_id = api.cipd.set_ref(instruction.package_name,
                                   instruction.version,
                                   [instruction.ref]).instance_id
    return cipd_uprev.PackageInstance(package_name=instruction.package_name,
                                      id=instance_id)


def RunSteps(api: RecipeApi, properties: cipd_uprev.Properties) -> None:
  release_tag_time = api.time.utcnow().isoformat()
  with api.deferrals.raise_exceptions_at_end():
    for instruction in properties.config.instructions:
      with api.step.nest('package %s' % instruction.package_name):
        validate(api, instruction)
        properties.response.old_versions.extend(
            [get_current_instance(api, instruction)])
        package_tags = {}
        if properties.config.release_version_tag:
          release_tag_key = properties.config.release_version_tag
          if release_tag_key == _CI_RELEASE_VERSION_TAG:
            release_tag_value = 'ci_{}'
          else:
            release_tag_value = 'ctp_{}'
          package_tags[release_tag_key] = release_tag_value.format(
              release_tag_time)
        with api.deferrals.defer_exceptions():
          package = uprev_package(api, instruction, package_tags)
          properties.response.new_versions.extend([package])
    for luci_instruction in properties.config.luci_instructions:  # pragma: no cover
      api.golucibin.execute_luciexe(luci_instruction.package_name,
                                    luci_instruction.ref, luci_instruction.args)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic-without-release-tagging',
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(instructions=[
                  cipd_uprev.Instruction(
                      package_name='chromiumos/infra/phosphorus/linux-amd64',
                      ref='foo-phosphorus-ref',
                      version='foo-phosphorus-version'),
                  cipd_uprev.Instruction(
                      package_name='infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
                      ref='foo-recipe-ref', version='foo-recipe-version'),
              ]))),
  )

  yield api.test(
      'basic-with-release-tagging',
      api.time.seed(123),
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(
                  instructions=[
                      cipd_uprev.Instruction(
                          package_name='chromiumos/infra/phosphorus/linux-amd64',
                          ref='foo-phosphorus-ref',
                          version='foo-phosphorus-version'),
                      cipd_uprev.Instruction(
                          package_name='infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
                          ref='foo-recipe-ref', version='foo-recipe-version'),
                  ], release_version_tag='ctp_release_version'))),
  )

  yield api.test(
      'basic-with-tag-error',
      api.time.seed(123),
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(
                  instructions=[
                      cipd_uprev.Instruction(
                          package_name='chromiumos/infra/phosphorus/linux-amd64',
                          ref='foo-phosphorus-ref',
                          version='foo-phosphorus-version'),
                      cipd_uprev.Instruction(
                          package_name='infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
                          ref='foo-recipe-ref', version='foo-recipe-version'),
                  ], release_version_tag='ctp_release_version'))),
      api.step_data(
          'package infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes.apply the "foo-recipe-ref" ref of the "infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes" package to "foo-recipe-version".cipd set-tag infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
          api.json.output({})),
      status='FAILURE',
  )

  yield api.test(
      'CI-packages-with-release-tagging',
      api.time.seed(123),
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(
                  instructions=[
                      cipd_uprev.Instruction(
                          package_name='chromiumos/infra/version_bumper/linux-amd64',
                          ref='foo-version_bumper-ref',
                          version='foo-version_bumper-version'),
                  ], release_version_tag='ci_release_version'))),
  )

  yield api.test(
      'missing-ref',
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(instructions=[
                  cipd_uprev.Instruction(
                      package_name='chromiumos/infra/phosphorus/linux-amd64',
                      version='foo-version')
              ]))),
      api.post_check(
          post_process.StepFailure,
          'package chromiumos/infra/phosphorus/linux-amd64.validate package instructions'
      ),
      status='FAILURE',
  )

  yield api.test(
      'missing-version',
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(instructions=[
                  cipd_uprev.Instruction(
                      package_name='chromiumos/infra/phosphorus/linux-amd64',
                      ref='foo-ref')
              ]))),
      api.post_check(
          post_process.StepFailure,
          'package chromiumos/infra/phosphorus/linux-amd64.validate package instructions'
      ),
      status='FAILURE',
  )

  yield api.test(
      'ref-does-not-exist',
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(instructions=[
                  cipd_uprev.Instruction(
                      package_name='chromiumos/infra/phosphorus/linux-amd64',
                      ref='prod', version='staging'),
              ]))),
      api.step_data(
          'package chromiumos/infra/phosphorus/linux-amd64.get instance ID of package "chromiumos/infra/phosphorus/linux-amd64" currently tagged with ref "prod".cipd describe chromiumos/infra/phosphorus/linux-amd64',
          api.cipd.example_error('no such ref')),
  )

  yield api.test(
      'ref-describe-fails-other-error',
      api.properties(
          cipd_uprev.Properties(
              config=cipd_uprev.Config(instructions=[
                  cipd_uprev.Instruction(
                      package_name='chromiumos/infra/phosphorus/linux-amd64',
                      ref='prod', version='staging'),
              ]))),
      api.step_data(
          'package chromiumos/infra/phosphorus/linux-amd64.get instance ID of package "chromiumos/infra/phosphorus/linux-amd64" currently tagged with ref "prod".cipd describe chromiumos/infra/phosphorus/linux-amd64',
          api.cipd.example_error('some other error')),
      status='INFRA_FAILURE',
  )
