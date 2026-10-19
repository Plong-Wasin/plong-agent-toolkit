---
name: phpstan-array-shapes
description: Generate PHPStan PHPDoc array shape type annotations for PHP code. Use this skill whenever the user asks about PHP array types, PHPDoc annotations, array shapes, PHPStan types, or wants to add type hints to PHP arrays. Also use when helping with type safety in PHP, fixing PHPStan errors, or documenting array structures.
---

# PHPStan Array Shapes

Generate accurate PHPStan PHPDoc annotations for array shapes to improve type safety in PHP code.

## Understanding Array Shapes

Array shapes in PHPStan allow you to define specific key-value structures where each key has its own type. This is more precise than general `array<Type>` syntax.

**Basic shape syntax:**
```php
/**
 * @param array{foo: int, bar: string} $data
 */
function process(array $data): void {}
```

## Key Concepts

### Optional Keys
Mark optional keys with `?`:
```php
array{foo: int, bar?: string}  // bar can be missing
```

### Tuple-style Arrays
Positional arrays with specific types:
```php
array{int, string}           // array with keys 0 and 1
list{int, string}            // same, but explicitly a list
array{0: int, 1?: string}    // explicit keys with optional
```

### Class Constant Keys
Use class constants as keys:
```php
array{Foo::BAR: int, Foo::BAZ?: string}
```

### Non-empty Variants
Ensure array has at least required elements:
```php
non-empty-array{foo: int, bar?: string}
non-empty-list{int, string}
```

## Array Shape vs General Arrays

**General arrays** - homogeneous types:
```php
array<string>       // values are all strings
array<int, User>    // int keys, User values
```

**Array shapes** - heterogeneous types per key:
```php
array{name: string, age: int, active: bool}
```

## Common Patterns

### API Response Shapes
```php
/**
 * @return array{success: bool, data?: array, error: string}
 */
function apiCall(): array {}
```

### Configuration Arrays
```php
/**
 * @param array{host: string, port?: int, timeout: int} $config
 */
```

### Database Result Shapes
```php
/**
 * @return array{id: int, email: string, created_at: string}
 */
```

## Nested Array Shapes

Nested arrays allow you to type complex multi-dimensional structures where keys contain other arrays.

### Basic Nested Structure
```php
/**
 * @param array{user: array{id: int, name: string}, meta: array{timestamp: int}} $data
 */
function processResponse(array $data): void {}
```

### Deep Nesting
For deeply nested structures, keep nesting array shapes:
```php
/**
 * @param array{
 *   user: array{
 *     id: int,
 *     profile: array{
 *       name: string,
 *       address: array{
 *         street: string,
 *         city: string
 *       }
 *     }
 *   }
 * } $data
 */
```

### Nested Lists (Arrays of Arrays)
Use `list{}` for sequential nested arrays:
```php
/**
 * @param array{users: list<array{id: int, name: string}>, total: int} $response
 */
function handleUserList(array $response): void {}
```

### Mixed Nested Types
Combine different array types in nested structures:
```php
/**
 * @param array{
 *   items: list<array{id: int, quantity: int}>,
 *   metadata: array{created: string, updated?: string}
 * } $order
 */
```

### Nested Optional Arrays
Mark nested arrays as optional with `?`:
```php
/**
 * @param array{
 *   required: array{foo: int},
 *   optional?: array{bar: string}
 * } $data
 */
```

### Using Type Aliases for Nested Structures
Break down complex nested types using `@phpstan-type`:
```php
/**
 * @phpstan-type Address array{street: string, city: string, zip: string}
 * @phpstan-type User array{id: int, name: string, address: Address}
 * @param array{user: User, meta: array{timestamp: int}} $data
 */
```

### Nested Array with Union Types
```php
/**
 * @param array{
 *   status: 'success'|'error',
 *   data: array{result: array{id: int, value: string}|null}
 * } $response
 */
```

### Arrays of Shapes (Homogeneous Nested)
When you have an array of identical structures:
```php
/**
 * @param array{comments: array<int, array{id: int, text: string, author: string}>} $post
 */
```

Or using list syntax:
```php
/**
 * @param array{comments: list<array{id: int, text: string, author: string}>} $post
 */
```

### Practical Examples

**E-commerce Order:**
```php
/**
 * @param array{
 *   order_id: int,
 *   customer: array{id: int, name: string, email: string},
 *   items: list<array{product_id: int, name: string, price: float, qty: int}>,
 *   shipping: array{address: string, city: string, zip: string, method: string},
 *   payment: array{method: 'card'|'bank'|'cash', status: string},
 *   totals: array{subtotal: float, tax: float, shipping: float, total: float}
 * } $order
 */
```

**API Response with Pagination:**
```php
/**
 * @return array{
 *   success: true,
 *   data: list<array{id: int, title: string, status: string}>,
 *   pagination: array{current_page: int, per_page: int, total: int, last_page: int}
 * }
 */
function getPosts(): array {}
```

**Configuration with Nested Settings:**
```php
/**
 * @param array{
 *   database: array{
 *     host: string,
 *     port: int,
 *     name: string,
 *     credentials: array{username: string, password: string}
 *   },
 *   cache: array{
 *     enabled: bool,
 *     driver: 'redis'|'memcached'|'file',
 *     config?: array<array-key, mixed>
 *   },
 *   logging: array{level: 'debug'|'info'|'error', channels: list<string>}
 * } $config
 */
```

## Offset Access Types

Access specific key types using bracket notation:
```php
/**
 * @phpstan-type UserData array{name: string, age: int}
 * @return UserData['age']  // returns int
 */
```

## Type Aliases

Use `@phpstan-type` for reusable shapes:
```php
/**
 * @phpstan-type Address array{street: string, city: string, zip: string}
 * @param Address $address
 */
```

Import from other classes:
```php
/**
 * @phpstan-import-type Address from User
 */
```

## Working with Generics

Array shapes work with templates:
```php
/**
 * @template T
 * @param array{items: array<T>, total: int} $result
 */
```

## Steps to Generate Array Shapes

1. **Identify the array structure** - Look at what keys exist and their value types
2. **Determine key optionality** - Which keys can be missing? Mark with `?`
3. **Choose appropriate wrapper** - `array{}`, `non-empty-array{}`, `list{}`, etc.
4. **Write the PHPDoc** - Place above function, method, or property
5. **Validate with PHPStan** - Ensure it catches type errors correctly

## Examples

### Simple User Data
```php
// Before:
/** @param array $user */
function updateUser(array $user) {}

// After:
/** @param array{id: int, name: string, email: string, active?: bool} $user */
```

### Enum Values
```php
/**
 * @param array{'admin'|'moderator'|'user': array{permissions: list<string>}} $roles
 */
```

### Real-World Nested Example (JSON API Response)
```php
// JSON response structure:
// {
//   "success": true,
//   "data": {
//     "users": [
//       {"id": 1, "name": "John", "posts": [{"id": 101, "title": "Hello"}]},
//       {"id": 2, "name": "Jane", "posts": []}
//     ],
//     "meta": {"page": 1, "total": 2}
//   }
// }

/**
 * @return array{
 *   success: true,
 *   data: array{
 *     users: list<array{
 *       id: int,
 *       name: string,
 *       posts: list<array{id: int, title: string}>
 *     }>,
 *     meta: array{page: int, total: int}
 *   }
 * }
 */
function fetchUsers(): array {}
```

## Best Practices

- **Be specific** - Use actual types, not `mixed` when possible
- **Use unions for enums** - `'red'|'green'|'blue'` instead of `string`
- **Mark optionality clearly** - Use `?` for keys that may be missing
- **Consider non-empty** - Use `non-empty-array{}` when arrays must have values
- **Document with aliases** - Use `@phpstan-type` for complex/reused shapes

## Common Mistakes to Avoid

❌ **Don't** use general array syntax for shapes:
```php
array<string, int>  // Wrong for {name: 1, age: 2}
```

✅ **Do** use shape syntax:
```php
array{name: int, age: int}
```

❌ **Don't** forget optional keys:
```php
array{foo: int, bar: string}  // bar is required!
```

✅ **Do** mark optionals:
```php
array{foo: int, bar?: string}  // bar can be missing
```

## When to Use Each Array Type

| Syntax | When to Use |
|--------|-------------|
| `array{key: Type}` | Named keys with specific types |
| `list{Type}` | Sequential numeric keys starting at 0 |
| `array{Type, Type}` | Tuple with fixed positions |
| `non-empty-array{}` | Array must have at least required keys |
| `array<KeyType, ValueType>` | Homogeneous key-value pairs |
