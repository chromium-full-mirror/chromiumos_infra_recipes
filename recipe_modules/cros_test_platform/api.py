# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for interacting with cros_test_platform."""

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.test_platform.steps.enumeration import EnumerationRequests
from PB.test_platform.steps.enumeration import EnumerationResponses
from PB.test_platform.steps.execution import ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponses
from PB.recipes.chromeos.test_platform.cros_test_platform import CrosTestPlatformProperties
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

# This exit code is returned by cros_test_platform runs that had an error but
# produced a response anyway.
_RETCODE_PARTIAL_RESPONSE = 2



class CrosTestPlatformCommand(recipe_api.RecipeApi):
  """Module for issuing cros_test_platform commands"""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._cmd = None
    # TODO(crbug.com/1030538): Remove the default once the label is populated
    # from the config.
    self._version = str(properties.version.cipd_label) or 'latest'

  def _run(self, subcommand, request, request_type, response_type):
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

      # Pre-execution logging is in a nested step so that the step closes before
      # the (possibly long) command execution.
      # This ensures that debugging information is not lost due to outer task
      # failure during the command execution (e.g., due to a timeout).
      with self.m.step.nest('pre-execution debug data') as ds:
        ds.logs['cmd'] = ' '.join([str(c) for c in cmd])
        ds.logs['request'] = json_format.MessageToJson(request)

      response = self.m.easy.stdout_jsonpb_step(
          subcommand,
          cmd,
          response_type,
          stdin=self.m.raw_io.input_text(json_format.MessageToJson(request)),
          test_output=response_type(),
          # TODO(crbug.com/1008921): Surface non-zero return codes as a step
          # warning.
          ok_ret=(0, _RETCODE_PARTIAL_RESPONSE))
      s.logs['response'] = json_format.MessageToJson(response)
      return response

  def enumerate(self, request):
    """Enumerate test cases via `enumerate` subcommand.

    Args:
      request: a EnumerationRequest.

    Returns: EnumerationResponse.
    """
    return self._run('enumerate', request, EnumerationRequests,
                     EnumerationResponses)

  def skylab_execute(self, request):
    """Execute work via `skylab-execute` subcommand.

    Args:
      request: a ExecuteRequest.

    Returns: ExecuteResponse.
    """
    return self._run('skylab-execute', request, ExecuteRequests,
                     ExecuteResponses)

  def execute_luciexe(self, properties, request):
    """Execute work via `luciexe` binary for cros_test_platform

    crbug.com/1112514: This is an alternative binary target for
    cros_test_platform which will eventually replace all the subcommands of the
    cros_test_platform binary.

    Args:
      request: a ExecuteRequests.
      properties: CrosTestPlatformProperties

    Returns: ExecuteResponses, Dict[string][string].
    """
    self._ensure_cros_test_platform()
    with self.m.step.nest('call binary') as s:
      cmd = self._cipd_dir.join('luciexe')
      # Simply use the same directory for the sub-build because I'm lazy and
      # because the intent is to unwrap the sub-build completely to replace this
      # parent build eventually.
      sub_cwd = self.m.path.start_dir
      input_json = sub_cwd.join('input.json')
      output_json = sub_cwd.join('output.json')

      self.m.file.write_proto('write input', input_json, request, 'JSONPB')

      # crbug.com/1119441: Clear out some output fields from a clone of the
      # parent Build that may have been already populated so far, because
      # sub_build() doesn't do it for us yet.
      build = build_pb2.Build()
      build.CopyFrom(self.m.buildbucket.build)
      for ofield in ['output', 'status', 'summary_markdown', 'steps']:
        build.ClearField(ofield)

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
            'launch luciexe',
            [cmd, '--', '-input_json', input_json, '-output_json', output_json],
            build,
        )

      responses = self.m.file.read_proto(
          'read output',
          output_json,
          ExecuteResponses,
          'JSONPB',
      )
      s.logs['responses'] = json_format.MessageToJson(responses)

      # Logs to be returned.
      suite_execution_logs = {}

      # For now the suite execution logic is going to be hidden behind a feature
      # flag.
      # Read the files outputted on the metrics.
      # they will be in:
      #   * sub_cwd/metric_logs/per_suite
      #   * sub_cwd/metric_logs/totals
      if ('chromeos.cros_infra_config.suite_execution_limited'
          in self.m.cros_infra_config.experiments or
          CrosTestPlatformProperties.SUITE_EXECUTION_LIMIT
          in properties.experiments):
        try:
          with self.m.step.nest('Read Execution Metrics'):
            totalsDir = sub_cwd.join('metric_logs/totals')
            perSuiteDir = sub_cwd.join('metric_logs/per_suites')

            # Read the final per suite report
            final_metrics = self.m.file.read_text(
                'read suite execution final metrics',
                totalsDir.join('final.csv'), include_log=False,
                test_data='suiteName,totalTestExecutionSeconds,completed,exceededExecutionLimit\ndefault,0,True,False'
            )

            suite_execution_logs['totals'] = final_metrics

            perSuiteLogPaths = self.m.file.listdir(
                'List Dir', perSuiteDir, test_data=['/tmp/default.csv'])
            for path in perSuiteLogPaths:
              # Read the final per suite report
              suite_metric = self.m.file.read_text(
                  'read suite execution final metrics', path, include_log=False,
                  test_data='suiteName,taskName,lastSeen,currentlySeenAt,delta,completed\ndefault,default,,12,True'
              )
              # Strip file type from name
              suite = self.m.path.basename(path).replace('.csv', '')

              suite_execution_logs[suite] = suite_metric
        # TODO(b/271176507): We don't want logging to be blocking as this will mean
        # loss of test results. Since suite_execution_limited is not fully
        # rolled out, this can be ignored for now.
        except StepFailure:  # pragma: nocover
          pass

      # If the experiment isn't on then suite_execution_logs will be an empty dict.
      return responses, suite_execution_logs

  def _ensure_cros_test_platform(self):
    """Ensure the cros_test_platform CLI is installed."""
    if self._cmd:
      return

    with self.m.step.nest('ensure cros_test_platform'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path.start_dir.join('cipd', 'cros_test_platform')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/cros_test_platform/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_dir = cipd_dir
        self._cmd = cipd_dir.join('cros_test_platform')

  def cipd_package_version(self):
    """Return the CTP CIPD package version (e.g. prod/staging/latest)."""
    return self._version
