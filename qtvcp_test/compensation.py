#!/usr/bin/env python
"""Copyright (C) 2009 Nick Drobchenko, nick@cnc-club.ru

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""
work_thread = 0.05 # work_thread means how often pins will be updated (sec)


import sys

# prepare height map
class Compensation :
	def __init__(self) :
		self.comp = {}
		self.x_coords = []
		self.y_coords = []
		if len(sys.argv)<2:
			print("ERROR! No input file name specified!")
			sys.exit()

		self.range_x,self.range_y, self.len_x,self.len_y = [],[], 0,0 

		self.filename = sys.argv[1]

		#self.reset()
		#print self.get_comp(10,10)

	
	def reset(self) :
		print("Call reset")
		f = open(self.filename,"r")
		probe_lines = f.readlines()

		self.comp = {}
		self.x_coords = []
		self.y_coords = []
		for line in probe_lines :
			coords = [float(i) for i in line.split()]
			x,y,z = coords[0:3]
			x,y = round(x,4), round(y,4)
			if x not in self.comp :  self.comp[x] = {}
			self.comp[x][y] = z
			if not x in self.x_coords : self.x_coords.append(x)
			if not y in self.y_coords : self.y_coords.append(y)
		self.x_coords.sort()	
		self.y_coords.sort()

		# check map integrity, map should be rectangular! 
		for x in self.x_coords :
			for y in self.y_coords :
				if not x in self.comp or not y in self.comp[x] :  
					print("ERROR! Map should be rectangular!\nCan not find point X %s Y %s"%(x,y))
					sys.exit()
		self.len_x = len(self.x_coords)
		self.range_x = range(self.len_x)
		self.len_y = len(self.y_coords)
		self.range_y = range(self.len_y)
		print(self.x_coords)
		for x in self.comp :
			print(x, "     ",self.comp[x])
		print(self.len_x, self.len_y)
		self.error = True

	def get_comp(self,x,y) :
			x = max(self.x_coords[0],min(self.x_coords[-1],x))
			y = max(self.y_coords[0],min(self.y_coords[-1],y))
			i = 0
			while i<self.len_x :
				if self.x_coords[i]>x : break
				i+=1
								
			j = 0
			while j<self.len_y :
				if self.y_coords[j]>y : break
				j+=1
		
			if i==self.len_x : i -= 1 
			if j==self.len_y : j -= 1 
			x2=self.x_coords[i]
			y2=self.y_coords[j]
						

			if i<self.len_x:
				x1 = self.x_coords[max(0,i-1)]
			else:
				x1 = x2	
			
			if j<self.len_y:
				y1 = self.y_coords[max(0,j-1)]
			else:
				y1 = y2	


			# now make bilinear interpolation of the points 
			if x1 != x2 :
				z1 = ((x2-x)*self.comp[x1][y1] + (x-x1)*self.comp[x2][y1])/(x2-x1)
				z2 = ((x2-x)*self.comp[x1][y2] + (x-x1)*self.comp[x2][y2])/(x2-x1)
			else:
				z1 = self.comp[x1][y1]
				z2 = self.comp[x1][y2]
			if y1 != y2 : 
				z1 = ((y2-y)*z1 + (y-y1)*z2)/(y2-y1)
				
			#print x2,y2,z1
			return z1	


	def run(self) :
		import hal, time
		
		h = hal.component("compensation")
		h.newpin("out", hal.HAL_FLOAT, hal.HAL_OUT)
		h.newpin("enable", hal.HAL_BIT, hal.HAL_IN)
		h.newpin("x-map", hal.HAL_FLOAT, hal.HAL_IN)
		h.newpin("y-map", hal.HAL_FLOAT, hal.HAL_IN)
		h.newpin("reset", hal.HAL_BIT, hal.HAL_IN)
		h.newpin("error", hal.HAL_BIT, hal.HAL_OUT)
		# ok, lets we are ready, lets go 
		h.ready()
		last_reset = h["reset"]
		try:
			while 1:
				try:
					time.sleep(work_thread)
					if h["enable"] :
						x=h['x-map']
						y=h['y-map']
						h["out"]=self.get_comp(x,y)
					else :	
						h["out"]=0
					if h["reset"]  and not last_reset:
							self.reset()
					last_reset = h["reset"]
				except KeyboardInterrupt :
					raise SystemExit	
				except : 
					h["error"] = False
				else :
					h["error"] = True	

		except KeyboardInterrupt:
	  	  raise SystemExit

comp = Compensation()
comp.run()
