# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for managing multiple parallel "worker" Buildbucket builds."""

# TODO(crbug/914992): Replace JSON messages once recipes protobuf support lands.

import json

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

BUILDBUCKET_PROJECT = 'chromeos'
BUILDBUCKET_SERVER = 'cr-buildbucket.appspot.com'


class Manager(object):
  """A Manager tracks the progress of one or more Buildbucket builds."""

  def __init__(self, api):
    """Initialize the Manager.

    Args:
      api (BuildManagerApi): The BuildManagerApi that instantiated this Manager.
    """
    self._api = api
    self._unscheduled = []
    self._scheduled_builds = []
    self._poll_update_times = {}

  def add_build(self, builder_id):
    """Adds a new ScheduleBuild request to the Manager.

    Builds will not be scheduled until |schedule_builds| is called.

    Args:
      builder_id (str): Canonical builder ID: "<project>/<bucket>/<builder>".
    """
    project, bucket, builder = builder_id.split('/')
    self._unscheduled.append({
        'builder': {
            'project': project,
            'bucket': bucket,
            'builder': builder,
        },
    })

  def schedule_builds(self, test_response=None):
    """Schedules all unscheduled builds."""
    resps = self._api._buildbucket_batch('schedule_build', self._unscheduled,
                                         test_response=test_response)
    for build_dict in resps:
      self._scheduled_builds.append(
          message_from_jsonpb_dict(build_pb2.Build, build_dict))
    self._unscheduled = []

  @property
  def scheduled_build_ids(self):
    """Returns a list of scheduled build IDs."""
    return [build.id for build in self._scheduled_builds]

  def poll(self):
    """Returns Builds that have been updated since the last call to 'poll'.

    Note: This will return all scheduled Builds immediately after a call to
    'schedule_builds'.

    Returns:
      List[build_pb2.Build]: All Builds that have been updated.
    """
    if not self._scheduled_builds:
      return []
    reqs = [{'id': build_id} for build_id in self.scheduled_build_ids]
    updated = []
    for build_dict in self._api._buildbucket_batch('get_build', reqs):
      build = message_from_jsonpb_dict(build_pb2.Build, build_dict)
      if self._poll_update_times.get(build.id) != build.update_time:
        self._poll_update_times[build.id] = build.update_time
        updated.append(build)
    return updated


class BuildManagerApi(recipe_api.RecipeApi):
  """A module for managing multiple parallel "worker" builds."""

  def new_manager(self):
    """Create a new Manager."""
    return Manager(self)

  def _buildbucket_batch(self, batch_type, requests, test_response=None):
    """Call Buildbucket Batch method.

    If any batched request fails, the whole step will fail.

    Args:
      batch_type (str): Batch type; a field name on BatchRequest.Request.
      requests (List[dict]): The requests to batch.
      test_response (dict): The response when testing. If it is a dict with
        exactly one key 'responses' then it is used as the BatchResponse, else
        it is copied as the response for each request.

    Returns:
      List[dict]: The responses.
    """
    method = 'buildbucket.v2.Builds.Batch'
    batch_req = {'requests': [{batch_type: req} for req in requests]}

    if test_response is None or test_response.keys() != ['responses']:
      if test_response is None:
        test_response = {}
      test_response = {
          'responses': [{
              batch_type: test_response
          }] * len(requests)
      }

    batch_resp = self.m.prpc.call_json(BUILDBUCKET_SERVER, method, batch_req,
                                       name='prpc %s %s' % (method, batch_type),
                                       test_output_data=test_response)

    batch_resps = batch_resp['responses']
    if len(batch_resps) != len(requests):
      self.m.step.active_result.presentation.status = self.m.step.FAILURE
      raise self.m.step.InfraFailure('got %d responses for %d requests' %
                                     (len(batch_resps), len(requests)))

    responses = []
    failures = []
    for req, resp in zip(requests, batch_resps):
      if 'error' in resp:
        failures.append('Error:\n%s\nRequest:\n%s' % (
            json.dumps(resp['error']),
            json.dumps(req),
        ))
      else:
        responses.append(resp[batch_type])

    if failures:
      presentation = self.m.step.active_result.presentation
      presentation.status = self.m.step.FAILURE
      presentation.logs['buildbucket failures'] = failures
      raise self.m.step.InfraFailure('buildbucket batch failure')

    return responses


def message_from_jsonpb_dict(message_type, dct):
  """Returns an instance of message_type populated from dct."""
  return json_format.Parse(
      json.dumps(dct), message_type(), ignore_unknown_fields=True)
