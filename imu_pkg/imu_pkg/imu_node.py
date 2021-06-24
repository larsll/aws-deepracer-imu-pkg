#!/usr/bin/env python

#################################################################################
#   Copyright Lars Ludvigsen. All Rights Reserved.          #
#                                                                               #
#   Licensed under the Apache License, Version 2.0 (the "License").             #
#   You may not use this file except in compliance with the License.            #
#   You may obtain a copy of the License at                                     #
#                                                                               #
#       http://www.apache.org/licenses/LICENSE-2.0                              #
#                                                                               #
#   Unless required by applicable law or agreed to in writing, software         #
#   distributed under the License is distributed on an "AS IS" BASIS,           #
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.    #
#   See the License for the specific language governing permissions and         #
#   limitations under the License.                                              #
#################################################################################

"""
imu_node.py

"""

import os
import threading
import json
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup

from BMI160_i2c import Driver
from BMI160_i2c import definitions

from deepracer_interfaces_pkg.msg import (IMUSensorMsg)
from imu_pkg import (constants)

class IMUNode(Node):
    """Node responsible for collecting the camera and LiDAR messages and publishing them
       at the rate of the camera sensor.
    """

    def __init__(self):
        """Create a IMUNode.
        """
        super().__init__("imu_node")
        self.get_logger().info("imu_node started.")
        self.stop_queue = threading.Event()

        # Publisher that sends combined sensor messages with camera data and LiDAR data
        # to inference node.
        self.imu_message_pub_cb_grp = ReentrantCallbackGroup()
        self.imu_message_publisher = self.create_publisher(IMUSensorMsg,
                                                            constants.IMU_MSG_TOPIC,
                                                            1,
                                                            callback_group=self.imu_message_pub_cb_grp)

        # Heartbeat timer.
        self.timer_count = 0
        self.timer = self.create_timer(5.0, self.timer_callback)

        self.get_logger().info("IMU node successfully created")


    def timer_callback(self):
        """Heartbeat function to keep the node alive.
        """
        self.get_logger().debug(f"Timer heartbeat {self.timer_count}")
        self.timer_count += 1

    def __enter__(self):
        """Called when the node object is created using the 'with' statement.
        Returns:
           IMUNode : self object returned.
        """
        try:

            self.get_logger().info('Trying to initialize the sensor...')
            self.sensor = Driver(constants.BMI160_ADDR, constants.I2C_BUS_ID) # change address if needed
            self.get_logger().info('Initialization done')

            # Defining the Range for Accelerometer and Gyroscope
            self.sensor.setFullScaleAccelRange(definitions.ACCEL_RANGE_4G, constants.ACCEL_RANGE_4G_FLOAT)
            self.sensor.setFullScaleGyroRange(definitions.GYRO_RANGE_250, constants.GYRO_RANGE_250_FLOAT)

            # Calibrating Accelerometer - assuming that it stands on 'flat ground'.
            # Gravity points downwards, hence Z should be calibrated to -1.
            self.sensor.autoCalibrateXAccelOffset(0)
            self.sensor.autoCalibrateYAccelOffset(0)
            self.sensor.autoCalibrateZAccelOffset(-1)

            self.sensor.setAccelOffsetEnabled(True)

        except Exception as ex:
            self.get_logger().info(f"Failed to create IMU monitor: {ex}")
            self.observer = None

        self.thread = threading.Thread(target=self.processor)
        self.thread.start()

        # Start IMU event monitor.
        return self

    def __exit__(self, ExcType, ExcValue, Traceback):
        """Called when the object is destroyed.
        """
        self.stop_queue.set()
        self.thread.join()

    def processor(self):
        rate = self.create_rate(constants.IMU_MSG_RATE)

        while not self.stop_queue.isSet():
            try:
                while rclpy.ok():
                    self.publish_imu_message()
                    rate.sleep()
            except Exception as ex:
                self.get_logger().info(f"Failed to create IMU message: {ex}")      

    def publish_imu_message(self):
        """Publish the sensor message when we get new data for the slowest sensor(LiDAR).
        """
        try:
            sensor_msg = IMUSensorMsg()
            data = self.sensor.getMotion6()
            
            # fetch all gyro and acclerometer values
            sensor_msg.g_x = data[0] / constants.CONVERSION_MASK_16BIT_FLOAT * constants.GYRO_RANGE_250_FLOAT
            sensor_msg.g_y = data[1] / constants.CONVERSION_MASK_16BIT_FLOAT * constants.GYRO_RANGE_250_FLOAT
            sensor_msg.g_z = data[2] / constants.CONVERSION_MASK_16BIT_FLOAT * constants.GYRO_RANGE_250_FLOAT
            
            sensor_msg.a_x = data[3] / constants.CONVERSION_MASK_16BIT_FLOAT * constants.ACCEL_RANGE_4G_FLOAT
            sensor_msg.a_y = data[4] / constants.CONVERSION_MASK_16BIT_FLOAT * constants.ACCEL_RANGE_4G_FLOAT
            sensor_msg.a_z = data[5] / constants.CONVERSION_MASK_16BIT_FLOAT * constants.ACCEL_RANGE_4G_FLOAT
            
            self.get_logger().debug('gz: {:+.0f}'.format(sensor_msg.g_x))

            self.imu_message_publisher.publish(sensor_msg)

        except Exception as ex:
            self.get_logger().error(f"Error in publishing sensor message: {ex}")


def main(args=None):
    rclpy.init(args=args)
    with IMUNode() as imu_node:
        executor = MultiThreadedExecutor()
        rclpy.spin(imu_node, executor)
    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    imu_node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
