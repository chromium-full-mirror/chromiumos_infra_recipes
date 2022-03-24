# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_paygen',
]

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.build_report import BuildReportBeta as BuildReport

from PB.chromite.api.payload import DLCImage, GenerationRequest
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


def RunSteps(api):
  standard_payload = build_pb2.Build(status='SUCCESS')
  # The absence of any DLC or MINIOS markers implies a standard payload for
  # the tested module's purposes.
  standard_payload.input.properties['requests'] = [
      MessageToDict(GenerationRequest()),
      MessageToDict(GenerationRequest())
  ]
  standard_payload.output.properties['payload_uris'] = [
      'gs://path/to/standard/payload',
      # Empty payload for minios skip.
      ''
  ]

  minios_and_dlc_payload = build_pb2.Build(status='SUCCESS')
  minios_and_dlc_payload.input.properties['requests'] = [
      MessageToDict(GenerationRequest(minios=True)),
      MessageToDict(GenerationRequest(tgt_dlc_image=DLCImage(dlc_id='dlc')))
  ]
  minios_and_dlc_payload.output.properties['payload_uris'] = [
      'gs://path/to/minios/payload', 'gs://path/to/dlc/payload'
  ]

  paygen_builds = [
      standard_payload,
      build_pb2.Build(status="FAILURE"),
      minios_and_dlc_payload,
  ]
  build_report = api.cros_paygen.create_paygen_build_report(paygen_builds)

  expected_build_report = [
      BuildReport.Payload(
          payload=BuildReport.BuildArtifact(
              uri=BuildReport.BuildArtifact.URI(
                  gcs='gs://path/to/standard/payload'),
              type=BuildReport.BuildArtifact.Type.PAYLOAD_DELTA,
              sha256='deadbeef',
          ),
          payload_type=BuildReport.Payload.PayloadType.PAYLOAD_TYPE_STANDARD,
          appid='appid',
          metadata_signature='signature',
          metadata_size=1337,
          size=1234,
          source_version='1.2.3',
          target_version='4.5.6',
      ),
      BuildReport.Payload(
          payload=BuildReport.BuildArtifact(
              uri=BuildReport.BuildArtifact.URI(
                  gcs='gs://path/to/minios/payload'),
              type=BuildReport.BuildArtifact.Type.PAYLOAD_DELTA,
              sha256='deadbeef',
          ),
          payload_type=BuildReport.Payload.PayloadType.PAYLOAD_TYPE_MINIOS,
          appid='appid',
          metadata_signature='signature',
          metadata_size=1337,
          size=1234,
          source_version='1.2.3',
          target_version='4.5.6',
      ),
      BuildReport.Payload(
          payload=BuildReport.BuildArtifact(
              uri=BuildReport.BuildArtifact.URI(gcs='gs://path/to/dlc/payload'),
              type=BuildReport.BuildArtifact.Type.PAYLOAD_DELTA,
              sha256='deadbeef',
          ),
          payload_type=BuildReport.Payload.PayloadType.PAYLOAD_TYPE_DLC,
          appid='appid',
          metadata_signature='signature',
          metadata_size=1337,
          size=1234,
          source_version='1.2.3',
          target_version='4.5.6',
      )
  ]
  api.assertions.assertEqual(build_report, expected_build_report)


def GenTests(api):
  json_data = """{
  "appid": "appid",
  "metadata_signature": "signature",
  "metadata_size": 1337,
  "size": 1234,
  "source_version": "1.2.3",
  "target_version": "4.5.6",
  "sha256_hex": "deadbeef",
  "is_delta": true
}"""

  yield api.test(
      'basic',
      api.step_data('gsutil cat gs://path/to/standard/payload.json',
                    stdout=api.raw_io.output(json_data)),
      api.step_data('gsutil cat gs://path/to/minios/payload.json',
                    stdout=api.raw_io.output(json_data)),
      api.step_data('gsutil cat gs://path/to/dlc/payload.json',
                    stdout=api.raw_io.output(json_data)))
