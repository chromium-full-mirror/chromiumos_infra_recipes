# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

from PB.chromiumos.checkpoint import RetryStep
from PB.recipe_modules.chromeos.checkpoint.tests.cascade import TestProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'checkpoint',
]

PROPERTIES = TestProperties

TESTS = [
    # Test that CREATE_BUILDSPEC forces all other orchestrator steps.
    ('create-buildspec-propagate-1', [RetryStep.CREATE_BUILDSPEC], [
        RetryStep.CREATE_BUILDSPEC, RetryStep.RUN_CHILDREN,
        RetryStep.LAUNCH_TESTS
    ]),
    ('create-buildspec-propagate-2',
     [RetryStep.CREATE_BUILDSPEC, RetryStep.RUN_CHILDREN], [
         RetryStep.CREATE_BUILDSPEC, RetryStep.RUN_CHILDREN,
         RetryStep.LAUNCH_TESTS
     ]),
    ('all-orch-steps-already-present', [
        RetryStep.CREATE_BUILDSPEC, RetryStep.RUN_CHILDREN,
        RetryStep.LAUNCH_TESTS
    ], [
        RetryStep.CREATE_BUILDSPEC, RetryStep.RUN_CHILDREN,
        RetryStep.LAUNCH_TESTS
    ]),
    ('create-buildspec-propagate-3',
     [RetryStep.CREATE_BUILDSPEC, RetryStep.LAUNCH_TESTS], [
         RetryStep.CREATE_BUILDSPEC, RetryStep.RUN_CHILDREN,
         RetryStep.LAUNCH_TESTS
     ]),
    # Test that RUN_CHILDREN and RUN_FAILED_CHILDREN force LAUNCH_TESTS.
    ('run-children-propagate', [RetryStep.RUN_CHILDREN],
     [RetryStep.RUN_CHILDREN, RetryStep.LAUNCH_TESTS]),
    ('run-failed-children-propagate', [RetryStep.RUN_FAILED_CHILDREN], [
        RetryStep.RUN_CHILDREN, RetryStep.RUN_FAILED_CHILDREN,
        RetryStep.LAUNCH_TESTS
    ]),
    # Checks that STAGE_ARTIFACTS forces all other builder steps.
    ('stage-artifats-propagate', [RetryStep.STAGE_ARTIFACTS], [
        RetryStep.STAGE_ARTIFACTS, RetryStep.PUSH_IMAGES,
        RetryStep.DEBUG_SYMBOLS, RetryStep.COLLECT_SIGNING, RetryStep.PAYGEN
    ]),
    # Checks that UPLOAD_PAYLOAD forces all other paygen steps.
    ('upload-payload-propagate', [RetryStep.UPLOAD_PAYLOAD],
     [RetryStep.UPLOAD_PAYLOAD, RetryStep.TEST_PAYLOAD])
]


def RunSteps(api: RecipeApi, properties: TestProperties):
  got = api.checkpoint.cascade(properties.steps)
  api.assertions.assertEqual(got, properties.expected_steps)


def GenTests(api):
  for test_name, steps, expected_steps in TESTS:
    yield api.test(
        test_name,
        api.properties(**{'$chromeos/checkpoint': {
            'retry': True,
        }}),
        api.properties(
            TestProperties(steps=steps, expected_steps=expected_steps)),
        api.post_process(post_process.DropExpectation),
    )
