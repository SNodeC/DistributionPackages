cmake_minimum_required(VERSION 3.20)
project(coreci_worker_checks NONE)
enable_testing()
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
file(GLOB cases CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py")
foreach(case IN LISTS cases)
  get_filename_component(name "${case}" NAME_WE)
  add_test(NAME "${name}" COMMAND "${Python3_EXECUTABLE}" "${case}")
  set_tests_properties("${name}" PROPERTIES
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../.."
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;TMPDIR=${CMAKE_BINARY_DIR}"
    LABELS adapters)
endforeach()
