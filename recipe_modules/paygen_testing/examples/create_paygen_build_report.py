# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.payload import Build
from PB.chromite.api.payload import DLCImage
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage
from PB.chromite.api.payload import UnsignedImage
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.build_report import URI
import PB.chromiumos.common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'paygen_testing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):

  class dotdict(dict):
    """dot.notation access to dictionary attributes.

    This is necessary because of the way the recipes engine handles request
    objects, and ensuring our test is able to replicate the code under test.
    """
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

  api.assertions.maxDiff = None
  build_report = [
      api.paygen_testing.create_paygen_build_report_payload(
          dotdict({
              'generation_request':
                  GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(channel='canary-channel')))
          }), 'gs://path/to/standard/payload'),
      api.paygen_testing.create_paygen_build_report_payload(
          dotdict({
              'generation_request':
                  GenerationRequest(
                      tgt_unsigned_image=UnsignedImage(
                          build=Build(channel='dev-channel')))
          }), None),
      api.paygen_testing.create_paygen_build_report_payload(
          build_pb2.Build(status='FAILURE'), None),
      api.paygen_testing.create_paygen_build_report_payload(
          dotdict({
              'generation_request':
                  GenerationRequest(
                      tgt_unsigned_image=UnsignedImage(
                          build=Build(channel='stable-channel')),
                      minios=True,
                  ),
          }), 'gs://path/to/minios/payload'),
      api.paygen_testing.create_paygen_build_report_payload(
          dotdict({
              'generation_request':
                  GenerationRequest(
                      tgt_dlc_image=DLCImage(
                          build=Build(channel='beta-channel'), dlc_id='dlc'))
          }), 'gs://path/to/dlc/payload', 1),
  ]

  expected_build_report = [
      BuildReport.Payload(
          payload=BuildReport.BuildArtifact(
              uri=URI(gcs='gs://path/to/standard/payload'),
              type=BuildReport.BuildArtifact.Type.PAYLOAD_DELTA,
              sha256='deadbeef',
          ),
          payload_type=BuildReport.Payload.PayloadType.PAYLOAD_TYPE_STANDARD,
          channel=common_pb2.Channel.CHANNEL_CANARY,
          appid='appid',
          metadata_signature='signature',
          metadata_size=1337,
          size=1234,
          source_version='1.2.3',
          target_version='4.5.6',
      ), None, None,
      BuildReport.Payload(
          payload=BuildReport.BuildArtifact(
              uri=URI(gcs='gs://path/to/minios/payload'),
              type=BuildReport.BuildArtifact.Type.PAYLOAD_DELTA,
              sha256='deadbeef',
          ),
          payload_type=BuildReport.Payload.PayloadType.PAYLOAD_TYPE_MINIOS,
          channel=common_pb2.Channel.CHANNEL_STABLE,
          appid='appid',
          metadata_signature='signature',
          metadata_size=1337,
          size=1234,
          source_version='1.2.3',
          target_version='4.5.6',
      ),
      BuildReport.Payload(
          payload=BuildReport.BuildArtifact(
              uri=URI(gcs='gs://path/to/dlc/payload'),
              type=BuildReport.BuildArtifact.Type.PAYLOAD_DELTA,
              sha256='deadbeef',
          ),
          payload_type=BuildReport.Payload.PayloadType.PAYLOAD_TYPE_DLC,
          channel=common_pb2.Channel.CHANNEL_BETA,
          appid='appid',
          metadata_signature='signature',
          metadata_size=1337,
          size=1234,
          source_version='1.2.3',
          target_version='4.5.6',
          recovery_key_version=1,
      )
  ]
  api.assertions.assertEqual(build_report, expected_build_report)


def GenTests(api: RecipeTestApi):
  json_data = '''{
  "appid": "appid",
  "metadata_signature": "signature",
  "metadata_size": 1337,
  "size": 1234,
  "source_version": "1.2.3",
  "target_version": "4.5.6",
  "sha256_hex": "deadbeef",
  "is_delta": true
}'''

  str_json_data = '''{
  "appid": "appid",
  "metadata_signature": "signature",
  "metadata_size": "1337",
  "size": "1234",
  "source_version": "1.2.3",
  "target_version": "4.5.6",
  "sha256_hex": "deadbeef",
  "is_delta": true
}'''

  yield api.test(
      'basic',
      api.step_data('gsutil cat gs://path/to/standard/payload.json',
                    stdout=api.raw_io.output(json_data)),
      api.step_data('gsutil cat gs://path/to/minios/payload.json',
                    stdout=api.raw_io.output(json_data)),
      api.step_data('gsutil cat gs://path/to/dlc/payload.json',
                    stdout=api.raw_io.output(json_data)))

  yield api.test(
      'int-parsing',
      api.step_data('gsutil cat gs://path/to/standard/payload.json',
                    stdout=api.raw_io.output(str_json_data)),
      api.step_data('gsutil cat gs://path/to/minios/payload.json',
                    stdout=api.raw_io.output(str_json_data)),
      api.step_data('gsutil cat gs://path/to/dlc/payload.json',
                    stdout=api.raw_io.output(str_json_data)))
