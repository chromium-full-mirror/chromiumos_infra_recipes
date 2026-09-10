# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test api.gerrit.create_flow_remote."""

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.gerrit import Flow
from PB.recipe_modules.chromeos.gerrit.gerrit import FlowAction
from PB.recipe_modules.chromeos.gerrit.gerrit import FlowStageExpression

DEPS = [
    'gerrit',
]


def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )
  flow_proto = Flow(
      stage_expressions=[
          FlowStageExpression(
              condition='{self} is label:Commit-Queue=0',
              action=FlowAction(
                  name='add-reviewer',
                  parameters=['cros-ec-champion@google.com'],
              ),
          ),
          FlowStageExpression(
              condition='{self} is is:abandoned',
              action=FlowAction(
                  name='add-reviewer',
                  parameters=['fqj@google.com'],
              ),
          ),
          FlowStageExpression(
              condition='{self} is status:merged',
              action=FlowAction(
                  name='add-reviewer',
                  parameters=['fqj@google.com'],
              ),
          ),
      ],
  )
  api.gerrit.create_flow_remote(gerrit_change, flow_proto)


def GenTests(api):
  yield api.test('basic')
