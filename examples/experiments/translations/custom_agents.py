import wallace
from custom_transformations import TranslationTransformation


class SimulatedAgent(wallace.agents.Agent):
    """A simulated agent that translates between French and English."""

    __mapper_args__ = {"polymorphic_identity": "simulated_agent"}

    def update(self, info_in):

        # Apply the translation transformation.
        transformation1 = TranslationTransformation()
        info_out = transformation1.apply(info_in)

        info_out.copy_to(self)
