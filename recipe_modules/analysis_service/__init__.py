DEPS = ['recipe_engine/step', 'cloud_pubsub']

from recipe_engine.recipe_api import Property

PROPERTIES = {
    'pubsub_project_id':
        Property(kind=str, default="chromeos-bot",
                 help="The Cloud Pub/Sub project to publish events to."),
    'pubsub_topic_id':
        Property(kind=str, default="analysis-service-events",
                 help="The Cloud Pub/Sub topic to publish events to.")
}
