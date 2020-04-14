# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.chromeos.test_platform import ctp_uprev

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = ctp_uprev.Properties

_RECIPE_CIPD_PACKAGE = (
    'infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes'
)
_GO_BINARY_CIPD_PACKAGE_PATTERN = 'chromiumos/infra/%s/linux-amd64'

_GO_BINARIES = ['cros_test_platform',
                'skylab_local_state',
                'phosphorus',
                'autotest_status_parser']


def validate(api, instruction):
  """Validate instructions for uprevving a specific package.

  Args:
    * instruction (ctp_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
  Raises:
    A ValueError if validation fails.
  """
  with api.step.nest('validate instructions %s' % instruction):
    if not instruction.ref:
      raise ValueError(
          'No ref to update for package %s' % instruction.package_name)
    if not instruction.version:
      raise ValueError(
          'No new version provided for package %s' % instruction.package_name)
    package_whitelist = _package_whitelist()
    if not instruction.package_name in package_whitelist:
      raise ValueError(
         'Invalid package %s - only the following packages are allowed: %s' %
         (instruction.package_name, package_whitelist))


def _package_whitelist():
  """Get the current version of the ref.

  Returns:
    list[str]
  """
  return ([_RECIPE_CIPD_PACKAGE] +
          [_GO_BINARY_CIPD_PACKAGE_PATTERN % name for name in _GO_BINARIES])


def get_current_instance(api, instruction):
  """Get the current version of the ref.

  Args:
    * instruction (ctp_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
  Returns:
    ctp_uprev.Instance
  Raises:
    A StepFailure if the CIPD tool call fails.
  """
  with api.step.nest('get instance ID of package "%s" with ref "%s"' %
                     (instruction.package_name, instruction.ref)):
    instance_id = api.cipd.describe(package_name=instruction.package_name,
                                    version=instruction.ref).pin.instance_id
    return ctp_uprev.PackageInstance(package_name=instruction.package_name,
                                     id=instance_id)


def uprev_package(api, instruction):
  """Change CIPD ref of a package according to the instructions.

  Args:
    * instruction (ctp_uprev.Instruction): A complete set of args for
      `cipd set-ref`.
  Returns:
    ctp_uprev.Instance
  Raises:
    A StepFailure if the CIPD tool call fails.
  """
  with api.step.nest('uprev the "%s" ref of the "%s" package to "%s"' %
      (instruction.ref, instruction.package_name, instruction.version)):
    instance_id = api.cipd.set_ref(
        instruction.package_name,
        instruction.version,
        [instruction.ref]).instance_id
    return ctp_uprev.PackageInstance(package_name=instruction.package_name,
                                     id=instance_id)


def RunSteps(api, properties):
  for instruction in properties.config.instructions:
    with api.step.nest('package %s' % instruction.package_name):
      validate(api, instruction)
      properties.response.old_versions.extend([
          get_current_instance(api, instruction)])
      properties.response.new_versions.extend([
          uprev_package(api, instruction)])


def GenTests(api):
  yield (
      api.test('basic') + #
      api.properties(
          ctp_uprev.Properties(
              config=ctp_uprev.Config(
                  instructions=[
                      ctp_uprev.Instruction(
                          package_name=
'chromiumos/infra/phosphorus/linux-amd64',
                          ref='foo-phosphorus-ref',
                          version='foo-phosphorus-version'),
                      ctp_uprev.Instruction(
                          package_name=
'infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
                          ref='foo-recipe-ref',
                          version='foo-recipe-version'),
                      ])))
  )
  yield (
      api.test('missing ref') + #
      api.properties(
          ctp_uprev.Properties(
              config=ctp_uprev.Config(
                  instructions=[
                      ctp_uprev.Instruction(
                          package_name=
'chromiumos/infra/phosphorus/linux-amd64',
                          version='foo-version')]))) + #
      api.expect_exception("ValueError")
  )
  yield (
      api.test('missing version') + #
      api.properties(
          ctp_uprev.Properties(
              config=ctp_uprev.Config(
                  instructions=[
                      ctp_uprev.Instruction(
                          package_name=
'chromiumos/infra/phosphorus/linux-amd64',
                          ref='foo-ref')]))) + #
      api.expect_exception("ValueError")
  )
  yield (
      api.test('invalid package') + #
      api.properties(
          ctp_uprev.Properties(
              config=ctp_uprev.Config(
                  instructions=[
                      ctp_uprev.Instruction(
                          package_name='invalid-package',
                          ref='foo-ref',
                          version='foo-version')]))) + #
      api.expect_exception("ValueError")
  )
