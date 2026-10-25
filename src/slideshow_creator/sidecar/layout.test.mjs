import {test} from 'node:test';
import assert from 'node:assert/strict';
import {textCollisions} from './layout.mjs';
test('overlapping labels block a diagram',()=>{
 assert.equal(textCollisions([{left:10,right:130,top:10,bottom:40,text:'Close notes'},{left:40,right:160,top:25,bottom:55,text:'Correct gaps'}]).length,1);
});
test('separated labels remain valid',()=>{
 assert.deepEqual(textCollisions([{left:10,right:130,top:10,bottom:40,text:'Close notes'},{left:140,right:260,top:10,bottom:40,text:'Correct gaps'}]),[]);
});
