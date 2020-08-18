# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api


from PB.test_platform.steps.enumeration import \
  EnumerationRequests, EnumerationResponses
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequests, SchedulerTrafficSplitResponses
from PB.test_platform.steps.execution import ExecuteRequests, ExecuteResponses

# This exit code is returned by cros_test_platform runs that had an error but
# produced a response anyway.
_RETCODE_PARTIAL_RESPONSE = 2


class CrosTestPlatformCommand(recipe_api.RecipeApi):
  """Module for issuing cros_test_platform commands"""

  def __init__(self, properties, **kwargs):
    super(CrosTestPlatformCommand, self).__init__(**kwargs)
    self._cmd = None
    # TODO(crbug.com/1030538): Remove the default once the label is populated
    # from the config.
    self._version = str(properties.version.cipd_label) or 'latest'

  def _run(self, subcommand, request, request_type, response_type,
           extra_args=None):
    """Generic subcommand runner for cros_test_platform.

    All cros_test_platform subcommands take the same basic commandline
    arguments.

    Args:
      subcommand: (str) subcommand to run.
      request: proto input request to subcommand.
      request_type: request must be of this type.
      response_type: response type proto.
      extra_args: [str] list of extra arguments to the command.

    Returns:
      Response, of type response_type.
    """
    with self.m.step.nest('call binary') as s:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      self._ensure_cros_test_platform()
      cmd = [
        self._cmd,
        subcommand,
        '-input_json',
        '/dev/stdin',
        '-output_json',
        '/dev/stdout',
      ]
      if extra_args:
        cmd += extra_args

      # Pre-execution logging is in a nested step so that the step closes before
      # the (possibly long) command execution.
      # This ensures that debugging information is not lost due to outer task
      # failure during the command execution (e.g., due to a timeout).
      with self.m.step.nest('pre-execution debug data') as ds:
        ds.logs['cmd'] = [' '.join([str(c) for c in cmd])]
        ds.logs['request'] = [json_format.MessageToJson(request)]

      response = self.m.easy.stdout_jsonpb_step(
          subcommand,
          cmd,
          response_type,
          stdin=self.m.raw_io.input_text(json_format.MessageToJson(request)),
          test_output=response_type(),
          # TODO(crbug.com/1008921): Surface non-zero return codes as a step
          # warning.
          ok_ret=(0, _RETCODE_PARTIAL_RESPONSE))
      s.logs['response'] = [json_format.MessageToJson(response)]
      return response

  def enumerate(self, request):
    """Enumerate test cases via `enumerate` subcommand.

    Args:
      request: a EnumerationRequest.

    Returns: EnumerationResponse.
    """
    return self._run('enumerate', request, EnumerationRequests,
                     EnumerationResponses)

  def scheduler_traffic_split(self, request):
    """Determine scheduler via `scheduler-traffic-split` subcommand.

    Args:
      request: a SchedulerTrafficSplitRequests.

    Returns: SchedulerTrafficSplitResponses.
    """
    return self._run(
        'scheduler-traffic-split', request, SchedulerTrafficSplitRequests,
        SchedulerTrafficSplitResponses, extra_args=['-rip-cautotest'])

  def skylab_execute(self, request):
    """Execute work via `skylab-execute` subcommand.

    Args:
      request: a ExecuteRequest.

    Returns: ExecuteResponse.
    """
    return self._run('skylab-execute', request, ExecuteRequests,
                     ExecuteResponses)

  def execute_luciexe(self, request):
    """Execute work via `luciexe` binary for cros_test_platform

    crbug.com/1112514: This is an alternative binary target for
    cros_test_platform which will eventually replace all the subcommands of the
    cros_test_platform binary.

    Args:
      request: a ExecuteRequests.

    Returns: ExecuteResponses.
    """
    self._ensure_cros_test_platform()
    with self.m.step.nest('call binary') as s:
      cmd = self._cipd_dir.join("luciexe")
      # Simply use the same directory for the sub-build because I'm lazy and
      # because the intent is to unwrap the sub-build completely to replace this
      # parent build eventually.
      sub_cwd = self.m.path['start_dir']
      input_json = sub_cwd.join("input.json")
      output_json = sub_cwd.join("output.json")

      self.m.file.write_proto("write input", input_json, request, 'JSONPB')

      # sub_build() raises StepFailure if the sub-build completes in FAILURE
      # and InfraFailure if sub-build completes in INFRA_FAILURE.
      #
      # crbug.com/1115207: We currently interpret all failures in the
      # sub-luciexe as InfraFailure because test failures are bubbled up later
      # in the summary step. As test summary updates are moved into the luciexe,
      # we will no longer need to return the responses from this sub_build()
      # invocation and will instead start surfacing test failures as
      # StepFailure.
      with self.m.context(cwd=sub_cwd, infra_steps=True):
        self.m.step.sub_build(
            "launch luciexe",
            [cmd, '--', '-input_json', input_json, '-output_json', output_json],
            self.m.buildbucket.build,
        )

      responses = self.m.file.read_proto(
          "read output",
          output_json,
          ExecuteResponses,
          'JSONPB',
      )
      s.logs['responses'] = [json_format.MessageToJson(responses)]
      return responses

  def _ensure_cros_test_platform(self):
    """Ensure the cros_test_platform CLI is installed."""
    if self._cmd:
      return

    with self.m.step.nest('ensure cros_test_platform'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'cros_test_platform')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/cros_test_platform/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_dir = cipd_dir
        self._cmd = cipd_dir.join('cros_test_platform')
