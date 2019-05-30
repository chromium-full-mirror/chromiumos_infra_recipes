# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.recipes.chromeos.crostfe import CrosTfeProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = CrosTfeProperties

def validate_request(api, properties):
  """Validate the CrosTfeProperties.

  Args:
    * api (object): See RunSteps documentation.
    * properties (CrosTfeProperties): The input request.

  Raises: An exception if there are invalid properties.
  """
  with api.step.nest('validate request'):
    if not properties.params.board:
      raise ValueError("params.board must be specified")

def enumerate_tests(api, properties):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * properties (CrosTfeProperties): The input request.

  Returns:
    TODO(akeshet): A list of EnumeratedTest protos.
  """
  with api.step.nest('enumerate tests'):
    return []

# TODO(akeshet): Move to a separate recipe_module that wraps the
# backend_selector binary, once that exists.
def select_backend(api, enumerated_tests, migration_config):
  """Select which backend (cautotest, skylab) will handle test requests.

  This step will be deleted once the entire device fleet has been migrated from
  cautotest to skylab.

  Args:
    * api (object): See RunSteps documentation.
    * enumerated_tests (list[EnumeratedTest proto]): tests to run.
    * migration_config (MigrationConfig proto): migration configuration.

  Raises: An exception if a backend cannot be selected for these requests (for
        instance, if the set of tests are too heterogenous to be handled by
        a single backend).

  Returns:
    TODO(akeshet): Enum(autotest, skylab) indication of backend to use.
  """
  with api.step.nest('select backend'):
    # TODO(akeshet): Replace with real backend selector script.
    return api.step(
        'backend selector',
        ['echo', 'skylab'],
        stdout=api.raw_io.output()
    ).stdout

def RunSteps(api, properties):
  validate_request(api, properties)
  enumerated_tests = enumerate_tests(api, properties)
  # TODO(akeshet): Populate migration_config from recipe configuration.
  migration_config = None
  backend = select_backend(api, properties, migration_config)
  if backend == 'autotest':
    raise NotImplementedError('autotest backend')
  elif backend == 'skylab':
    raise NotImplementedError('skylab backend')
  else:
    raise ValueError('invalid backend %s' % backend)


def GenTests(api):
  yield (api.test('basic skylab') + #
         api.properties(CrosTfeProperties(params={'board': 'test_board'})) + #
         api.step_data('select backend.backend selector',
                       stdout=api.raw_io.output('skylab')) + #
         api.expect_exception('NotImplementedError'))

  yield (api.test('basic autotest') + #
         api.properties(CrosTfeProperties(params={'board': 'test_board'})) + #
         api.step_data('select backend.backend selector',
                       stdout=api.raw_io.output('autotest')) + #
         api.expect_exception('NotImplementedError'))

  yield (api.test('invalid backend') + #
         api.properties(CrosTfeProperties(params={'board': 'test_board'})) + #
         api.step_data('select backend.backend selector',
                       stdout=api.raw_io.output('foobar')) + #
         api.expect_exception('ValueError'))

  yield (api.test('board_param_missing') + #
         api.properties(CrosTfeProperties(params={'board': ''})) + #
         api.expect_exception('ValueError'))
