# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

from google.protobuf.json_format import MessageToDict
import itertools
import json
from os import path

from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from PB.recipes.chromeos.paygen import PaygenProperties
from PB.chromite.api.payload import Build, GenerationRequest, SignedImage
from PB.chromiumos.common import DeltaType

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from PB.recipe_engine import result as result_pb2

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_paygen',
    'cros_release_util',
    'cros_storage',
    'easy',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = PaygenOrchestratorProperties


def _summarize_failed_builds(failures):
  # Truncate the list of failures per section to keep the summary under
  # Buildbucket's 4000 byte limit on the summary_markdown field.
  # To be removed when https://crbug.com/1063398 is resolved.
  summary_markdown = ''
  for failure in failures:
    line = 'https://cr-buildbucket.appspot.com/build/{}'.format(failure.id)
    if len(summary_markdown) + len(line) < 3990:
      summary_markdown += ('\n' + line)
    else:
      # Abruptly truncate to avoid INFRA_FAILURE.
      summary_markdown += '\n...'
      break
  return summary_markdown


def py2_MessageToJson(obj):
  # TODO(b/217973414): Delete once we don't need to fix the separator spacing
  # between py2 and py3 MessageToJson and replace usages with MessageToJson.
  return json.dumps(
      MessageToDict(obj), separators=(',', ': '), indent=2, sort_keys=True)


def RunSteps(api, properties):
  api.easy.log_parent_step()

  # Set default values for unspecified properties.
  delta_types = properties.delta_types
  delta_types = delta_types or api.cros_paygen.default_delta_types

  # Get the current paygen configuration.
  with api.step.nest('discovering payload configuration') as pres:
    configured_payloads = []

    for delta_type, channel in itertools.product(delta_types,
                                                 properties.channels):

      delta_t_str, channel_str = (
          DeltaType.Name(delta_type),
          api.cros_release_util.channel_strip_prefix(channel))

      cfgs = api.cros_paygen.get_builder_configs(properties.builder_name,
                                                 delta_type=delta_t_str,
                                                 channel=channel_str)
      configured_payloads.extend(cfgs)

    pres.logs['%s configured sources' % len(configured_payloads)] = (
        json.dumps(configured_payloads, sort_keys=True, separators=(',', ':'),
                   indent=2))

    # If no payloads are configured return (that was easy!).
    if not configured_payloads:
      pres.step_text = 'no configurations matched in payload.json'
      return

  # Get all the artifacts in the source(s) and target locations.
  target_artifacts, source_artifacts = [], []
  for channel in properties.channels:

    # e.g. beta-channel, beta
    long_chan_name, short_chan_name = (
        api.cros_release_util.channel_to_long_string(channel),
        api.cros_release_util.channel_strip_prefix(channel))

    with api.step.nest('examining %s' % long_chan_name):

      # Iterate the configured payloads and find artifacts at each source.
      with api.step.nest('source artifacts'):
        # Create Source Image definitions based upon the configuration alone.
        for payload_cfg in configured_payloads:
          if payload_cfg['channel'] == short_chan_name:
            found_arts = api.cros_storage.discover_gs_artifacts(
                path.join('gs://' + properties.src_bucket, long_chan_name,
                          payload_cfg['builder_name'],
                          payload_cfg['chrome_os_version']),
                parse_types=api.cros_storage.image_types)
            source_artifacts.extend([x.to_proto() for x in found_arts])

      # Discover the target images for this channel.
      with api.step.nest('target artifacts'):
        found_arts = api.cros_storage.discover_gs_artifacts(
            path.join('gs://' + properties.src_bucket, long_chan_name,
                      properties.builder_name,
                      properties.target_chromeos_version),
            parse_types=api.cros_storage.image_types)
        target_artifacts.extend([x.to_proto() for x in found_arts])

  # Match configuration with discovered artifacts.
  with api.step.nest('discovered artifacts') as pres:
    pres.logs['target_artifacts'] = [
        py2_MessageToJson(x) for x in target_artifacts
    ]
    pres.logs['source_artifacts'] = [
        py2_MessageToJson(x) for x in source_artifacts
    ]

  # Aka: "GenerationRequests".
  gen_reqs = []

  # Find the src and tgt artifacts applicable for each configured payload
  # and construct the child requests. Report missing artifacts.
  # TODO(crbug.com/1122854): Missing artifacts are silently ignored.
  with api.step.nest('pairing artifacts') as pres:

    # Do N2N testing payloads.
    gen_reqs.extend(
        api.cros_paygen.get_n2n_requests(target_artifacts,
                                         properties.dest_bucket, True,
                                         properties.dryrun))

    # Do configured delta payloads.
    for payload_cfg in configured_payloads:
      delta_gen_reqs = api.cros_paygen.get_delta_requests(
          payload_cfg, source_artifacts, target_artifacts,
          properties.dest_bucket, True, properties.dryrun)
      gen_reqs.extend(delta_gen_reqs)
    pres.logs['%s deltas' % len(delta_gen_reqs)] = [
        py2_MessageToJson(x) for x in delta_gen_reqs
    ]

    # Do full payloads.
    full_gen_reqs = api.cros_paygen.get_full_requests(target_artifacts,
                                                      properties.dest_bucket,
                                                      True, properties.dryrun)
    pres.logs['%s full' % len(full_gen_reqs)] = [
        py2_MessageToJson(x) for x in full_gen_reqs
    ]
    gen_reqs.extend(full_gen_reqs)

    if not gen_reqs:
      pres.step_text = 'No payload pairs (src->tgt) found.'
      return
    else:
      pres.step_text = '%s payloads found.' % len(gen_reqs)

  # Determine hardware tests to run for each payload.
  paygen_reqs = []
  for gen_req in gen_reqs:
    au_test_configs = api.cros_paygen.create_au_test_configs(
        gen_req, configured_payloads,
        delta_test_override=properties.delta_payload_test_override,
        full_test_override=properties.full_payload_test_override)
    paygen_reqs.append(
        PaygenProperties.PaygenRequest(generation_request=gen_req,
                                       autoupdate_test_configs=au_test_configs))

  # Schedule child builders, and wait for them to finish.
  res = api.cros_paygen.run_paygen_builders(paygen_reqs)

  # Present results.
  with api.step.nest('results') as pres:
    suc = [x for x in res if x.status == common_pb2.SUCCESS]
    fail = [x for x in res if x.status != common_pb2.SUCCESS]
    pres.step_text = '%s of %s passed' % (len(suc), (len(suc) + len(fail)))

    with api.step.nest('set `payloads` output property'):
      payloads = api.cros_paygen.create_paygen_build_report(res)
      payloads_json = [py2_MessageToJson(payload) for payload in payloads]
      api.easy.set_properties_step(payloads=payloads_json)

  if fail:
    # Give a failure markdown with the failed paygen jobs.
    return result_pb2.RawResult(
        status=common_pb2.FAILURE,
        summary_markdown='{}\n{}'.format(pres.step_text,
                                         _summarize_failed_builds(fail)))


def GenTests(api):

  def get_props(delta_types=None, builder_name='coral',
                target_chromeos_version='13505.15.0', channels=None):
    delta_types = delta_types or ['OMAHA']
    channels = channels or ['CHANNEL_DEV', 'CHANNEL_BETA']
    return api.properties(delta_types=delta_types, builder_name=builder_name,
                          target_chromeos_version=target_chromeos_version,
                          channels=channels)

  good_paygen_cfg = api.cros_paygen.test_paygen(
      'discovering payload configuration.get paygen json.gsutil cat',
      api.cros_paygen.EXAMPLE_PAYGEN_JSON)

  def paygen_child_data(child_num):
    paygen_child_data = build_pb2.Build(id=8922054662172514000 + child_num,
                                        status='SUCCESS')
    paygen_child_data.output.properties['payload_uris'] = [
        'gs://path/to/payload'
    ]

    paygen_child_data.input.properties['requests'] = [
        {
            'generation_request':
                MessageToDict(
                    GenerationRequest(
                        tgt_signed_image=SignedImage(
                            build=Build(channel='canary-channel'))))
        },
    ]

    return paygen_child_data

  payload_json_data = """{
  "appid": "appid",
  "metadata_signature": "signature",
  "metadata_size": 1337,
  "size": 1234,
  "source_version": "1.2.3",
  "target_version": "4.5.6",
  "sha256_hex": "deadbeef",
  "is_delta": true
}"""

  def repeated_step_data(step_name, stdout, n):
    return [
        api.step_data('{}{}'.format(step_name, ' (%d)' % n if n > 1 else ''),
                      stdout=stdout) for n in range(1, n + 1)
    ]

  yield api.test(
      'basic', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'),
      api.buildbucket.simulated_collect_output(
          [paygen_child_data(x) for x in range(15)],
          'running children.collect'),
      *repeated_step_data(
          'results.set `payloads` output property.gsutil cat gs://path/to/payload.json',
          api.raw_io.output(payload_json_data), 13))

  yield api.test(
      'some-failures', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(id=8922054662172514000 + x, status='FAILURE')
          for x in range(16)
      ], 'running children.collect'),
      api.post_check(post_process.StatusFailure),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'))

  yield api.test('no-payloads', get_props(builder_name='goobolywhobbly'),
                 good_paygen_cfg, api.post_check(post_process.StatusSuccess))

  # Successful lists but don't find a suitable pair in get_requests().
  yield api.test(
      'no-pairs', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.15.0/'
          'ChromeOS-factory-R87-13505.15.0-coral.tar.xz'),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DoesNotRun, 'running children'))

  # Verify many builds failing gets truncated.
  summary = _summarize_failed_builds(
      [build_pb2.Build(id=8922054662172514000, status='FAILURE')] * 70)
  assert len(summary) < 4000
