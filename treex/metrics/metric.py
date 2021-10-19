import functools
import typing as tp
from abc import abstractmethod

import jax.numpy as jnp
import treeo as to
from rich.text import Text

from treex import types, utils
from treex.treex import Treex

M = tp.TypeVar("M", bound="Metric")


class MetricMeta(to.TreeMeta):
    def __call__(cls, *args, **kwargs) -> "Metric":
        metric = super().__call__(*args, **kwargs)
        metric = tp.cast(Metric, metric)

        # save initial state
        metric._initial_state = {
            field: getattr(metric, field)
            for field, metadata in metric.field_metadata.items()
            if metadata.node and field != "_initial_state"
        }

        return metric


class Metric(Treex, metaclass=MetricMeta):
    """
    Encapsulates metric logic and state. Metrics accumulate state between calls such
    that their output value reflect the metric as if calculated on the whole data
    given up to that point.
    """

    _initial_state: tp.Dict[str, tp.Any] = types.MetricState.node()

    def __init__(
        self,
        on: tp.Optional[types.IndexLike] = None,
        name: tp.Optional[str] = None,
        dtype: tp.Optional[jnp.dtype] = None,
    ):
        """
        Arguments:
            on: A string or integer, or iterable of string or integers, that
                indicate how to index/filter the `y_true` and `y_pred`
                arguments before passing them to `call`. For example if `on = "a"` then
                `y_true = y_true["a"]`. If `on` is an iterable
                the structures will be indexed iteratively, for example if `on = ["a", 0, "b"]`
                then `y_true = y_true["a"][0]["b"]`, same for `y_pred`. For more information
                check out [Keras-like behavior](https://poets-ai.github.io/elegy/guides/modules-losses-metrics/#keras-like-behavior).
        """

        self._labels_filter = (on,) if isinstance(on, (str, int)) else on
        self.name = name if name is not None else utils._get_name(self)
        self.dtype = dtype if dtype is not None else jnp.float32

    def __call__(self, **kwargs) -> tp.Any:
        if self._labels_filter is not None:
            if "y_true" in kwargs and kwargs["y_true"] is not None:
                for index in self._labels_filter:
                    kwargs["y_true"] = kwargs["y_true"][index]

            if "y_pred" in kwargs and kwargs["y_pred"] is not None:
                for index in self._labels_filter:
                    kwargs["y_pred"] = kwargs["y_pred"][index]

        # update cumulative state
        self.update(**kwargs)

        # compute batch metrics
        module = to.copy(self)
        module.reset()
        module.update(**kwargs)
        return module.compute()

    def reset(self):
        self.__dict__.update(self._initial_state)

    @abstractmethod
    def update(self, **kwargs) -> None:
        ...

    @abstractmethod
    def compute(self) -> tp.Any:
        ...

    def __init_subclass__(cls):
        super().__init_subclass__()

        # add call signature
        old_call = cls.__call__

        @functools.wraps(cls.update)
        def new_call(self: M, *args, **kwargs) -> M:
            if len(args) > 0:
                raise TypeError(
                    f"All arguments to {cls.__name__}.__call__ should be passed as keyword arguments."
                )

            return old_call(self, *args, **kwargs)

        cls.__call__ = new_call
