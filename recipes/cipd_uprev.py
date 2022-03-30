# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.chromeos import cipd_uprev
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = cipd_uprev.Properties

_CI_RELEASE_VERSION_TAG = 'ci_release_version'

def validate(api, instruction):
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

def get_current_instance(api, instruction):
  """Get the current version of the ref.

  Args:
    * instruction (cipd_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
  Returns:
    cipd_uprev.Instance
  Raises:
    A StepFailure if the CIPD tool call fails.
  """
  with api.step.nest('get instance ID of package "%s" with ref "%s"' %
                     (instruction.package_name, instruction.ref)):
    instance_id = api.cipd.describe(package_name=instruction.package_name,
                                    version=instruction.ref).pin.instance_id
    return cipd_uprev.PackageInstance(package_name=instruction.package_name,
                                      id=instance_id)

def uprev_package(api, instruction, package_tags=None):
  """Change CIPD ref of a package according to the instructions.

  Args:
    * instruction (cipd_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
    * package_tags: Tags to add to the package.
  Returns:
    cipd_uprev.Instance
  Raises:
    A StepFailure if the CIPD tool call fails.
  """
  package_tags = package_tags or {}
  with api.step.nest(
      'uprev the "%s" ref of the "%s" package to "%s"' %
      (instruction.ref, instruction.package_name, instruction.version)):
    for tag_key, tag_value in package_tags.items():
      api.cipd.set_tag(instruction.package_name, instruction.version,
                       {tag_key: tag_value})
    instance_id = api.cipd.set_ref(instruction.package_name,
                                   instruction.version,
                                   [instruction.ref]).instance_id
    return cipd_uprev.PackageInstance(package_name=instruction.package_name,
                                      id=instance_id)


def RunSteps(api, properties):
  release_tag_time = api.time.utcnow().isoformat()
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
      properties.response.new_versions.extend(
          [uprev_package(api, instruction, package_tags)])


def GenTests(api):
  yield api.test(
      'basic without release tagging',
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
      'basic with release tagging',
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
      'CI packages with release tagging',
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
      'missing ref',
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
  )

  yield api.test(
      'missing version',
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
  )
