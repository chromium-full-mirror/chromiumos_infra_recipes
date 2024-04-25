# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for issuing result flow commands"""

from google.protobuf import json_format

from PB.test_platform.result_flow.common import PubSubConfig
from PB.test_platform.result_flow.ctp import CTPRequest
from PB.test_platform.result_flow.ctp import CTPResponse
from PB.test_platform.result_flow.publish import PublishRequest
from PB.test_platform.result_flow.publish import PublishResponse
from PB.test_platform.result_flow.test_runner import TestRunnerRequest
from PB.test_platform.result_flow.test_runner import TestRunnerResponse
from recipe_engine import recipe_api


class ResultFlowCommand(recipe_api.RecipeApi):

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._cmd = None
    self._version = str(properties.version.cipd_label) or 'latest'
    if not self._version:  # pragma: no cover
      raise ValueError('No version label provided for '
                       'result_flow CIPD package.')

  def _run(self, subcommand, request, request_type, response_type):
    """Generic subcommand runner for result flow.

    Args:
      subcommand: (str) subcommand to run
      request: proto input request to subcommand
      request_type: request must be of this type
      response_type: response will be interpreted as this type
    Returns:
      JSON proto of response_type
    """
    with self.m.step.nest('call `result_flow`') as presentation:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      presentation.logs['request'] = json_format.MessageToJson(request)
      self._ensure_result_flow()
      cmd = [
          self._cmd,
          subcommand,
          '-input_json',
          '/dev/stdin',
      ]
      stdin = self.m.raw_io.input_text(json_format.MessageToJson(request))
      cmd += [
          '-output_json',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(subcommand, cmd, response_type,
                                                stdin=stdin,
                                                test_output=response_type(),
                                                ok_ret=(0,))
      presentation.logs['response'] = json_format.MessageToJson(response)
      return response

  def publish(self, project_id, topic_id, build_type,
              should_poll_for_completion=False, parent_uid=''):
    """Run the result_flow to publish build's own build ID to Pubsub.

    Args:
      * project_id (str): The project name
      * topic_id (str): The topic name
      * build_type (str): Allowed values are "ctp" and "test_runner"
      * should_poll_for_completion (bool): If true, the consumers should not ACK the message until the build is complete.
      * parent_uid (str): An attribute placed inside the message
    Returns:
      JSON proto of test_platform.result_flow.PublishResponse
    """
    req = PublishRequest(build_id=self.m.buildbucket.build.id,
                         should_poll_for_completion=should_poll_for_completion,
                         parent_uid=parent_uid)
    PubSubConfig(project=project_id, topic=topic_id)
    if build_type == 'ctp':
      req.ctp.project = project_id
      req.ctp.topic = topic_id
    elif build_type == 'test_runner':
      req.test_runner.project = project_id
      req.test_runner.topic = topic_id
    else:
      raise ValueError(
          'Unknown build_type %s, the only supported values are "ctp" and "test_runner"'
          % build_type)
    return self._run('publish', req, PublishRequest, PublishResponse)

  def pipe_ctp_data(self, request):
    """Pipe CTP data to TestPlanRun table in BQ.

    Args:
      * request: a test_platform.result_flow.CTPRequest
    Returns:
      JSON proto of test_platform.result_flow.CTPResponse
    """
    return self._run('pipe-ctp-data', request, CTPRequest, CTPResponse)

  def pipe_test_runner_data(self, request):
    """Pipe test runner data to TestRun/TestCase tables in BQ.

    Args:
      * request: a test_platform.result_flow.TestRunnerRequest
    Returns:
      JSON proto of test_platform.result_flow.TestRunnerResponse
    """
    return self._run('pipe-test-runner-data', request, TestRunnerRequest,
                     TestRunnerResponse)

  def _ensure_result_flow(self):
    """Ensure the result_flow CLI is installed."""
    if self._cmd:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure result_flow'):
        cipd_dir = self.m.path.start_dir.joinpath('cipd', 'result_flow')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/result_flow/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir / 'result_flow'
