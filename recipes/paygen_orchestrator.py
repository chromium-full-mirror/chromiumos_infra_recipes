# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

import itertools
import json
from os import path
from typing import Callable
from typing import Dict
from typing import List

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson
from google.protobuf.json_format import Parse

from PB.chromite.api.payload import Build as ChromiteBuild
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import DeltaType
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.paygen import PaygenProperties
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_reporting',
    'cros_release_util',
    'cros_storage',
    'easy',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = PaygenOrchestratorProperties


def RunSteps(api: RecipeApi, properties: PaygenOrchestratorProperties):
  # Parse all properties, defaulting the values if not set.
  delta_types = properties.delta_types or api.paygen_orchestration.default_delta_types
  paygen_mpa = properties.paygen_mpa or False
  minios = properties.minios
  keyset = properties.keyset

  # Since this job is intended to be run via a release build, log the
  # parent's build ID.
  api.easy.log_parent_step()

  # Get the current payload configuration.
  with api.step.nest('discovering payload configuration') as pres:
    configured_payloads = []

    for delta_type, channel in itertools.product(delta_types,
                                                 properties.channels):

      delta_t_str, channel_str = (
          DeltaType.Name(delta_type),
          api.cros_release_util.channel_strip_prefix(channel))

      cfgs = api.paygen_orchestration.get_builder_configs(
          properties.builder_name, delta_type=delta_t_str, channel=channel_str)
      configured_payloads.extend(cfgs)

    pres.logs['%s configured sources' % len(configured_payloads)] = (
        json.dumps(configured_payloads, sort_keys=True, separators=(',', ':'),
                   indent=2))

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
    pres.logs['target_artifacts'] = [MessageToJson(x) for x in target_artifacts]
    pres.logs['source_artifacts'] = [MessageToJson(x) for x in source_artifacts]

  # Aka: "GenerationRequests".
  gen_reqs = []

  # Split out the artifacts into buckets: n2n, delta, full.

  # Find the src and tgt artifacts applicable for each configured payload
  # and construct the child requests. Report missing artifacts.
  # TODO(crbug.com/1122854): Missing artifacts are silently ignored.
  with api.step.nest('pairing artifacts') as pres:

    # Do N2N testing payloads.
    n2n_gen_reqs = api.paygen_orchestration.get_n2n_requests(
        target_artifacts, properties.dest_bucket, True, properties.dryrun,
        minios=minios, keyset=keyset)
    pres.logs['%s n2n' %
              len(n2n_gen_reqs)] = [MessageToJson(x) for x in n2n_gen_reqs]
    gen_reqs.extend(n2n_gen_reqs)

    # Do configured delta payloads.
    delta_gen_reqs = []
    for payload_cfg in configured_payloads:
      delta_gen_reqs.extend(
          api.paygen_orchestration.get_delta_requests(
              payload_cfg, source_artifacts, target_artifacts,
              properties.dest_bucket, True, properties.dryrun, minios=minios,
              keyset=keyset))
    gen_reqs.extend(delta_gen_reqs)

    pres.logs['%s deltas' %
              len(delta_gen_reqs)] = [MessageToJson(x) for x in delta_gen_reqs]

    # Do full payloads.
    full_gen_reqs = api.paygen_orchestration.get_full_requests(
        target_artifacts, properties.dest_bucket, True, properties.dryrun,
        minios=minios, keyset=keyset)
    pres.logs['%s full' %
              len(full_gen_reqs)] = [MessageToJson(x) for x in full_gen_reqs]
    gen_reqs.extend(full_gen_reqs)

    if properties.local_signing:
      for gen_req in gen_reqs:
        gen_req.use_local_signing = properties.local_signing
        gen_req.docker_image = properties.docker_image

    if not gen_reqs:
      pres.step_text = 'No payload pairs (src->tgt) found.'
      return None
    pres.step_text = '%s payloads found.' % len(gen_reqs)

  # Determine hardware tests to run for each payload.
  paygen_reqs = []
  for gen_req in gen_reqs:
    paygen_reqs.append(
        PaygenProperties.PaygenRequest(generation_request=gen_req))

  # Schedule child builders, and wait for them to finish.
  res = api.paygen_orchestration.run_paygen_builders(
      paygen_reqs, paygen_mpa=paygen_mpa,
      use_split_paygen=properties.use_split_paygen)

  # Present results.
  with api.step.nest('results') as pres:
    suc = [x for x in res if x.status == common_pb2.SUCCESS]
    fail = [x for x in res if x.status != common_pb2.SUCCESS]
    pres.step_text = '%s of %s passed' % (len(suc), (len(suc) + len(fail)))

    with api.step.nest('set `payloads` output property'):
      payloads = []
      for run in res:
        if run.status != common_pb2.SUCCESS or 'payloads' not in run.output.properties:
          continue
        payloads.extend(run.output.properties['payloads'])
      payloads_json = [MessageToJson(payload) for payload in payloads]
      api.easy.set_properties_step(payloads=payloads_json)

  if properties.publish_to_pubsub:
    api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_PAYGEN, '')
    with api.build_reporting.step_reporting(
        BuildReport.StepDetails.STEP_OVERALL, raise_on_failed_publish=True):
      api.build_reporting.publish(
          BuildReport(payloads=[
              Parse(MessageToJson(payload), BuildReport.Payload())
              for payload in payloads
          ]))

  if fail:
    infra_fail = [x for x in fail if x.status == common_pb2.INFRA_FAILURE]
    fail = [x for x in fail if x.status != common_pb2.INFRA_FAILURE]

    infra_summary = '\ninfra_failure: {}\n'.format(
        _summarize_failed_builds(infra_fail)) if infra_fail else ''
    summary_markdown = 'paygenie failures\n{}\n{}{}'.format(
        pres.step_text, infra_summary, _summarize_failed_builds(fail))
    # Truncate the list of failures per section to keep the summary under
    # Buildbucket's 4000 byte limit on the summary_markdown field.
    # To be removed when https://crbug.com/1063398 is resolved.
    if len(summary_markdown) >= 4000:
      summary_markdown = summary_markdown[:3995] + '\n...'
    # Give a failure markdown with the failed paygen jobs.
    return result_pb2.RawResult(
        status=common_pb2.INFRA_FAILURE if infra_fail else common_pb2.FAILURE,
        summary_markdown=summary_markdown)
  return None


def _summarize_failed_builds(failures: List[Build]) -> str:
  # Truncate the list of failures per section to keep the summary under
  # Buildbucket's 4000 byte limit on the summary_markdown field.
  # To be removed when https://crbug.com/1063398 is resolved.
  summary_markdown = ''
  for failure in failures:
    line = 'https://cr-buildbucket.appspot.com/build/{}'.format(failure.id)
    summary_markdown += ('\n' + line)
  return summary_markdown


def GenTests(api: RecipeTestApi):

  def get_props(
      delta_types: List[str] = None,
      builder_name: str = 'coral',
      target_chromeos_version: str = '13505.15.0',
      channels: List[str] = None,
      pubsub: bool = False,
      override_qs_account: str = None,
      local_signing: bool = False,
      docker_image: str = None,
      paygen_mpa: bool = False,
  ) -> Callable[[PaygenOrchestratorProperties], TestData]:
    delta_types = delta_types or ['OMAHA']
    channels = channels or ['CHANNEL_DEV', 'CHANNEL_BETA']
    return api.properties(delta_types=delta_types, builder_name=builder_name,
                          target_chromeos_version=target_chromeos_version,
                          channels=channels, publish_to_pubsub=pubsub,
                          override_qs_account=override_qs_account,
                          local_signing=local_signing,
                          docker_image=docker_image, paygen_mpa=paygen_mpa)

  good_paygen_cfg = api.paygen_orchestration.test_paygen(
      'discovering payload configuration.get paygen json.gsutil cat',
      api.paygen_orchestration.EXAMPLE_PAYGEN_JSON)

  def paygen_child_data(child_num: int) -> Build:
    paygen_child_data = build_pb2.Build(id=8922054662172514000 + child_num,
                                        status='SUCCESS')
    paygen_child_data.output.properties['payloads'] = [{
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }, {
        'appid': 'appid',
        'channel': 'CHANNEL_CANARY',
        'metadataSignature': 'signature',
        'metadataSize': '1337',
        'payload': {
            'sha256': 'deadbeef',
            'type': 'PAYLOAD_DELTA',
            'uri': {
                'gcs': 'gs://path/to/payload'
            }
        },
        'payloadType': 'PAYLOAD_TYPE_STANDARD',
        'size': '1234',
        'sourceVersion': '1.2.3',
        'targetVersion': '4.5.6'
    }]

    paygen_child_data.input.properties['requests'] = [
        {
            'generation_request':
                MessageToDict(
                    GenerationRequest(
                        tgt_signed_image=SignedImage(
                            build=ChromiteBuild(channel='canary-channel'))))
        },
    ]

    return paygen_child_data

  def SummaryMarkdownLength(check: Callable[[str, bool], bool],
                            step_odict: Dict[str, Step]):
    """Assert that the summary markdown is less than 4000 chars."""
    summary_markdown = step_odict['$result']['failure']['humanReason']
    check('summary markdown < 4000 chars', len(summary_markdown) < 4000)

  build_message = api.buildbucket.ci_build_message(
      project='chromeos', bucket='release', builder='paygen-orchestrator')

  yield api.test(
      'basic',
      get_props(),
      good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'),
      api.buildbucket.simulated_collect_output(
          [paygen_child_data(x) for x in range(23)],
          'running children.collect'),
  )

  yield api.test(
      'use-local-signing',
      get_props(
          local_signing=True,
          docker_image='signing:latest',
      ),
      good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'),
      api.buildbucket.simulated_collect_output(
          [paygen_child_data(x) for x in range(23)],
          'running children.collect'),
  )

  yield api.test(
      'basic-with-pubsub',
      get_props(pubsub=True),
      good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'),
      # Status overall started.
      api.post_check(post_process.MustRun,
                     'build status pubsub update.publish message'),
      # Paygen.
      api.post_check(post_process.MustRun,
                     'build status pubsub update (2).publish message'),
      # Status overall completed.
      api.post_check(post_process.MustRun,
                     'build status pubsub update (3).publish message'),
      api.buildbucket.simulated_collect_output(
          [paygen_child_data(x) for x in range(23)],
          'running children.collect'),
  )

  yield api.test(
      'some-failures',
      get_props(),
      good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(id=8922054662172514000 + x,
                          status=('FAILURE' if x % 2 == 0 else 'SUCCESS'))
          for x in range(21)
      ], 'running children.collect'),
      api.post_check(SummaryMarkdownLength),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'),
      status='FAILURE',
  )

  yield api.test(
      'truncate-failures',
      get_props(),
      api.buildbucket.build(build_message),
      api.paygen_orchestration.test_paygen(
          'discovering payload configuration.get paygen json.gsutil cat',
          api.paygen_orchestration.EXAMPLE_PAYGEN_JSON_BIG),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.buildbucket.simulated_collect_output(
          [
              build_pb2.Build(
                  id=8922054662172514000 + x,
                  status=('INFRA_FAILURE' if x % 2 == 0 else 'SUCCESS'))
              for x in range(10)
          ] + [
              build_pb2.Build(id=8922054662172514000 + 10 + x,
                              status=('FAILURE' if x % 2 == 0 else 'SUCCESS'))
              for x in range(
                  300
              )  # Make sure to include more results than payloads to avoid KeyErrors.
          ],
          'running children.collect'),
      api.post_check(SummaryMarkdownLength),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test('no-payloads', get_props(builder_name='goobolywhobbly'),
                 good_paygen_cfg, api.buildbucket.build(build_message))

  # Successful lists but don't find a suitable pair in get_requests().
  yield api.test(
      'no-pairs', get_props(), good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.15.0/'
          'ChromeOS-factory-R87-13505.15.0-coral.tar.xz'),
      api.post_check(post_process.DoesNotRun, 'running children'))

  yield api.test(
      'no-deltas',
      get_props(),
      good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.paygen_orchestration.test_paygen(
          'discovering payload configuration.get paygen json.gsutil cat',
          api.paygen_orchestration.NO_DELTA_PAYGEN_JSON),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.buildbucket.simulated_collect_output(
          [paygen_child_data(x) for x in range(5)], 'running children.collect'),
  )

  # TODO(b/305046854): Temporarily allow MPA bot pool overrides.
  yield api.test(
      'paygen-mpa',
      get_props(paygen_mpa=True),
      good_paygen_cfg,
      api.buildbucket.build(build_message),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.buildbucket.simulated_collect_output(
          [paygen_child_data(x) for x in range(23)],
          'running children.collect'),
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'request', ['"builder": "paygen-mpa"']),
      api.post_process(post_process.DropExpectation),
  )
