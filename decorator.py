import time
import logging

# Set up basic logging config
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def log_and_time(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        logging.info(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed = end_time - start_time
        logging.info(f"{func.__name__} returned {result} in {elapsed:.6f} seconds")
        return result
    return wrapper

@log_and_time
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return int(a + b)

@log_and_time
def subtract(a: int, b: int) -> int:
    """Subtract two numbers"""
    return int(a - b)

@log_and_time
def multiply(a: int = 5, b: int = 6) -> int:
    """Multiply two numbers"""
    return a * b


# Store functions in a dictionary
function_dictionary = {
    'add': add,
    'subtract': subtract,
    'multiply': multiply
}

# Example usage
if __name__ == "__main__":
    # Method 1: Call functions using dictionary
    print("Method 1: Using dictionary access")
    result1 = function_dictionary['add'](5, 3)
    print(f"5 + 3 = {result1}")
    
    result2 = function_dictionary['subtract'](2, 3)
    print(f"2 - 3 = {result2}")

    result3 = function_dictionary['multiply'](a=2, b=3)
    print(f"2 * 3 = {result3}")
