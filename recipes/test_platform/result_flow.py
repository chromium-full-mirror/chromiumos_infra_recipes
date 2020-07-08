from PB.test_platform import result_flow
from PB.recipes.chromeos.test_platform.result_flow import \
  ResultFlowProperties

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'result_flow',
]

PROPERTIES = ResultFlowProperties


def execution_steps(api, properties):
  """Runs result_flow binary.

  Args:
  * properties: ResultFlowProperties instance.

  Raises:
  * InfraFailure.
  """
  with api.step.nest('execution steps'):
    if properties.ctp_flow:
      req = result_flow.ctp.CTPRequest(ctp=properties.ctp_flow.source,
                                       test_plan_run=properties.ctp_flow.target)
      if properties.HasField('deadline'):
        req.deadline.MergeFrom(properties.deadline)
      resp = api.result_flow.ctp(req)
      properties.response.state = resp.state


def RunSteps(api, properties):
  execution_steps(api, properties)

  if properties.response.state != result_flow.common.SUCCEEDED:
    with api.step.nest('build status'):
      raise api.step.StepFailure('Pipeline failed with status: %s' %
                                 str(properties.response.state))


def GenTests(api):

  def _run_test_step_with_state(state):
    return (api.step_data(
        'execution steps.call `result_flow`.ctp', stdout=api.raw_io.output(
            json_format.MessageToJson(
                result_flow.ctp.CTPResponse(state=state)))))

  def _canned_ctp_config():
    return {
        'source': {
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
        'target': {
            'bq': {
                'project': 'foo-project',
                'dataset': 'foo-dataset',
                'table': 'foo-table',
            }
        }
    }

  yield api.test(
      'success w/o deadline',
      api.properties(ResultFlowProperties(ctp_flow=_canned_ctp_config())),
      _run_test_step_with_state(result_flow.common.SUCCEEDED),
  )

  yield api.test(
      'success with deadline',
      api.properties(
          ResultFlowProperties(ctp_flow=_canned_ctp_config(),
                               deadline=timestamp_pb2.Timestamp(seconds=55))),
      _run_test_step_with_state(result_flow.common.SUCCEEDED),
  )

  yield api.test(
      'failed',
      api.properties(ResultFlowProperties(ctp_flow=_canned_ctp_config())),
      _run_test_step_with_state(result_flow.common.FAILED))

  yield api.test(
      'timed out',
      api.properties(ResultFlowProperties(ctp_flow=_canned_ctp_config())),
      _run_test_step_with_state(result_flow.common.TIMED_OUT))
