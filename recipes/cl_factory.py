# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Used to create sweeping changes by creating CLs in many repos."""

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.cl_factory import ClFactoryProperties

PROPERTIES = ClFactoryProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api, properties):
  gerrit_changes = api.buildbucket.build.input.gerrit_changes
  if not gerrit_changes:
    raise ValueError('Gerrit changes to apply must be specified.')

  if not properties.repo_regex:
    raise ValueError(
        'Projects to operate on must be specified by the '
        'repo_regex property.')

  if not properties.command:
    raise ValueError('A command property must specify how to modify the repos.')

  if not properties.message_template:
    raise ValueError(
        'A message_template property must specify how to create '
        'commit messages')

  with api.step.nest('running...') as pres:
    pres.step_text = 'yes I ran'


def GenTests(api):
  cls = [
      common_pb2.GerritChange(host='chromium.googlesource.com',
                              project='chromiumos/config',
                              change=1234),
      common_pb2.GerritChange(host='chrome-internal.googlesource.com',
                              project='chromeos/program/galaxy',
                              change=1234),
  ]

  def build(changes=True):
    build_message = api.buildbucket.ci_build_message(project='chromeos',
                                                     bucket='infra',
                                                     builder='cl_factory')
    if changes:
      build_message.input.gerrit_changes.extend(cls)

    return api.buildbucket.build(build_message)

  yield api.test(
      'basic',
      build(),
      api.properties(ClFactoryProperties(
          repo_regex = ['src/project/galaxy'],
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
          command = 'echo "hello world"',
          message_template = 'Fix audio config',
      )),
  )

  yield api.test(
      'no_gerrit_changes_specified',
      build(changes=False),
      api.properties(ClFactoryProperties(
          repo_regex = ['src/project/galaxy'],
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
          command = 'echo "hello world"',
          message_template = 'Fix audio config',
      )),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          '.*Gerrit changes to apply must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_repos_specified',
      build(),
      api.properties(ClFactoryProperties(
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
          command = 'echo "hello world"',
          message_template = 'Fix audio config',
      )),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          '.*Projects to operate on must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_command_specified',
      build(),
      api.properties(ClFactoryProperties(
          repo_regex = ['src/project/galaxy'],
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
          message_template = 'Fix audio config',
      )),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE, '.*A command property must specify.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_message_template_specified',
      build(),
      api.properties(ClFactoryProperties(
          repo_regex = ['src/project/galaxy'],
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
          command = 'echo "hello world"',
      )),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          '.*A message_template property must specify.*'),
      api.post_process(post_process.DropExpectation),
  )
