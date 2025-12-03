import functools
import inspect
import math


class BoundsError(ValueError):
    pass


class OptionError(ValueError):
    pass


class ConditionalError(ValueError):
    pass


POSITIVE = (0, math.inf)
NEGATIVE = (-math.inf, 0)


def verify_bounds(value, bounds, message=None, error_type=BoundsError):
    if message is None:
        message = "Value '{}' was not in the allowed range: ({}, {})"
    if len(bounds) != 2:
        raise ValueError("There must only be two items per argument to define a bound range")
    for bound in bounds:
        if not isinstance(bound, (int, float)):
            raise TypeError("The range values passed ({}) are not ints or floats".format(bounds))
    if bounds[0] > value or value > bounds[1]:
        raise error_type(message.format(
            value, bounds[0], bounds[1]))


def options(**options_kwargs):
    message = options_kwargs.pop('message', "Argument '{}' passed to '{}' was not one of the allowed options: {}")
    error_type = options_kwargs.pop('error_type', OptionError)

    def decorator(func):

        sig = inspect.signature(func)
        parameter_options = sig.bind_partial(**options_kwargs).arguments

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            passed_values = sig.bind(*args, **kwargs).arguments
            for name, value in passed_values.items():
                if name in parameter_options:
                    if value not in parameter_options[name]:
                        raise error_type(message.format(
                            value, func.__name__, parameter_options[name]))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def bounds(**bounds_kwargs):
    message = bounds_kwargs.pop('message', "Argument '{}' passed to '{}' was not in the range: ({}, {})")
    error_type = bounds_kwargs.pop('error_type', BoundsError)

    for key, values in bounds_kwargs.items():
        if len(values) != 2:
            raise ValueError("There must only be two items per argument to define a bound range")
        for value in values:
            if not isinstance(value, (int, float)):
                raise TypeError("The range values passed ({}) are not ints or floats".format(values))

    def decorator(func):

        sig = inspect.signature(func)
        start_stop = sig.bind_partial(**bounds_kwargs).arguments

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            passed_values = sig.bind(*args, **kwargs).arguments
            for name, value in passed_values.items():
                if name in start_stop:
                    start = start_stop[name][0]
                    stop = start_stop[name][1]
                    if start > value or value > stop:
                        raise error_type(message.format(
                            value, func.__name__, start, stop))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def conditional(**conditions_kwargs):
    message = conditions_kwargs.pop('message', "Condition self.{} != {} which is required to continue")
    error_type = conditions_kwargs.pop('error_type', ConditionalError)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for key, value in conditions_kwargs.items():
                if getattr(args[0], key) != value:
                    raise error_type(message.format(key, value))
            return func(*args, **kwargs)
        return wrapper
    return decorator
