# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.recipes.chromeos.test_platform.result_flow import \
  ResultFlowProperties
from PB.test_platform import result_flow
from PB.test_platform.result_flow import ctp, test_runner

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'result_flow',
]


PROPERTIES = ResultFlowProperties


def run_test_runner_flow(api, config, deadline):
  with api.step.nest('process test_runner builds'):
    req = test_runner.TestRunnerRequest(test_runner=config.test_runner,
                                        test_run=config.test_run,
                                        test_case=config.test_case)
    if deadline:
      req.deadline.MergeFrom(deadline)
    return api.result_flow.pipe_test_runner_data(req).state


def run_test_ctp_flow(api, config, deadline):
  with api.step.nest('process CTP builds'):
    req = ctp.CTPRequest(ctp=config.ctp, test_plan_run=config.test_plan_run)
    if deadline:
      req.deadline.MergeFrom(deadline)
    return api.result_flow.pipe_ctp_data(req).state


def _verify_flow(config, flow):
  if flow == 'test_runner_flow':
    return (config.test_runner.pubsub.subscription and
            config.test_runner.bb.builder and config.test_run.bq.table and
            config.test_case.bq.table)
  if flow == 'ctp_flow':
    return (config.ctp.pubsub.subscription and config.ctp.bb.builder and
            config.test_plan_run.bq.table)
  raise ValueError(flow)  # pragma:nocover


def RunSteps(api, properties):
  if _verify_flow(config=properties.test_runner_flow, flow='test_runner_flow'):
    properties.response.state = run_test_runner_flow(
        api=api, config=properties.test_runner_flow,
        deadline=properties.deadline
        if properties.HasField('deadline') else None)

  if _verify_flow(config=properties.ctp_flow, flow='ctp_flow'):
    properties.response.state = run_test_ctp_flow(
        api=api, config=properties.ctp_flow, deadline=properties.deadline
        if properties.HasField('deadline') else None)

  if properties.response.state != result_flow.common.SUCCEEDED:
    with api.step.nest('build status'):
      raise api.step.StepFailure('Pipeline failed with status: %s' %
                                 str(properties.response.state))


def GenTests(api):

  def _run_ctp_flow_with_state(state):
    return (api.step_data(
        'process CTP builds.call `result_flow`.pipe-ctp-data',
        stdout=api.raw_io.output(
            json_format.MessageToJson(ctp.CTPResponse(state=state)))))

  def _run_test_runner_flow_with_state(state):
    return (api.step_data(
        'process test_runner builds.call `result_flow`.pipe-test-runner-data',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                test_runner.TestRunnerResponse(state=state)))))

  def _canned_ctp_config():
    return {
        'ctp': {
            'pubsub': {
                'project': 'foo-project',
                'topic': 'foo-topic',
                'subscription': 'foo-subscription',
                'max_receiving_messages': 50
            },
            'bb': {
                'host': 'cr-buildbucket.appspot.com',
                'project': 'chromeos',
                'bucket': 'testplatform',
                'builder': 'cros_test_platform'
            },
            'fields': [
                'id', 'status', 'input.properties', 'output.properties',
                'create_time', 'start_time', 'end_time'
            ],
        },
        'test_plan_run': {
            'bq': {
                'project': 'foo-project',
                'dataset': 'foo-dataset',
                'table': 'foo-table',
            }
        }
    }

  def _canned_test_runner_config():
    return {
        'test_runner': {
            'pubsub': {
                'project': 'foo-project',
                'topic': 'foo-topic',
                'subscription': 'foo-subscription',
                'max_receiving_messages': 50
            },
            'bb': {
                'host': 'cr-buildbucket.appspot.com',
                'project': 'chromeos',
                'bucket': 'test_runner',
                'builder': 'test_runner',
            },
            'fields': [
                'id', 'status', 'input.properties', 'output.properties',
                'create_time', 'start_time', 'end_time'
            ],
        },
        'test_run': {
            'bq': {
                'project': 'foo-project',
                'dataset': 'foo-dataset',
                'table': 'foo-table-test-run',
            }
        },
        'test_case': {
            'bq': {
                'project': 'foo-project',
                'dataset': 'foo-dataset',
                'table': 'foo-table-test-case',
            }
        }
    }

  yield api.test(
      'ctp-result-flow-success-without-deadline',
      api.properties(ResultFlowProperties(ctp_flow=_canned_ctp_config())),
      _run_ctp_flow_with_state(result_flow.common.SUCCEEDED),
  )

  yield api.test(
      'ctp-result-flow-success-with-deadline',
      api.properties(
          ResultFlowProperties(ctp_flow=_canned_ctp_config(),
                               deadline=timestamp_pb2.Timestamp(seconds=55))),
      _run_ctp_flow_with_state(result_flow.common.SUCCEEDED),
  )

  yield api.test(
      'ctp-result-flow-failed',
      api.properties(ResultFlowProperties(ctp_flow=_canned_ctp_config())),
      _run_ctp_flow_with_state(result_flow.common.FAILED),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'ctp-result-flow-timed-out',
      api.properties(ResultFlowProperties(ctp_flow=_canned_ctp_config())),
      _run_ctp_flow_with_state(result_flow.common.TIMED_OUT),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'test_runner-result-flow-success-without-deadline',
      api.properties(
          ResultFlowProperties(test_runner_flow=_canned_test_runner_config())),
      _run_test_runner_flow_with_state(result_flow.common.SUCCEEDED),
  )

  yield api.test(
      'test_runner-result-flow-success-with-deadline',
      api.properties(
          ResultFlowProperties(test_runner_flow=_canned_test_runner_config(),
                               deadline=timestamp_pb2.Timestamp(seconds=55))),
      _run_test_runner_flow_with_state(result_flow.common.SUCCEEDED),
  )
